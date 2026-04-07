"""LinkedIn post publishing helpers built on top of the Playwright session."""

import asyncio
import logging
from typing import Optional

from .base import BaseScraper
from ..models import PublishResult
from ..callbacks import ProgressCallback, SilentCallback
from ..core.exceptions import ScrapingError

logger = logging.getLogger(__name__)


class PostPublisher(BaseScraper):
    """Browser automation for personal and company LinkedIn posts."""

    def __init__(self, page, callback: Optional[ProgressCallback] = None):
        super().__init__(page, callback or SilentCallback())

    async def publish_person_post(
        self,
        text: str,
        dry_run: bool = True,
        visibility: str = "Anyone",
    ) -> PublishResult:
        """Create a post from the signed-in member profile."""
        await self.callback.on_start("publish_person_post", "https://www.linkedin.com/feed/")

        try:
            await self.navigate_and_wait("https://www.linkedin.com/feed/")
            await self.ensure_logged_in()
            await self.page.wait_for_selector("main", timeout=10000)
            await self.wait_and_focus(1)
            await self.callback.on_progress("Opened feed", 15)

            opened = await self._open_person_composer()
            if not opened:
                raise ScrapingError(
                    "Could not open the personal post composer automatically. "
                    "LinkedIn is not exposing the composer reliably in the current DOM/session."
                )

            await self._wait_for_person_composer()

            await self.callback.on_progress("Composer opened", 40)
            await self._fill_post_text(text)
            await self.callback.on_progress("Post text filled", 65)

            result = PublishResult(
                actor="person",
                dry_run=dry_run,
                composer_opened=True,
                text_filled=True,
                submitted=False,
                visibility=visibility,
                destination_url=self.page.url,
                message="Personal post composer is ready."
                if dry_run
                else "Personal post submitted.",
            )

            if dry_run:
                await self.callback.on_complete("publish_person_post", result)
                return result

            await self._submit_post()
            result.submitted = True
            result.post_url = self.page.url
            await self.callback.on_complete("publish_person_post", result)
            return result
        except Exception as e:
            await self.callback.on_error(e)
            raise

    async def publish_company_post(
        self,
        company_url: str,
        text: str,
        dry_run: bool = True,
        visibility: str = "Anyone",
    ) -> PublishResult:
        """Create a post from a company page where the current member has admin access."""
        await self.callback.on_start("publish_company_post", company_url)

        try:
            admin_share_url = self._build_company_share_url(company_url)
            await self.navigate_and_wait(admin_share_url)
            await self.ensure_logged_in()
            await self.page.wait_for_selector("body", timeout=10000)
            await self.wait_and_focus(1)
            await self._dismiss_generic_modals()
            await self.callback.on_progress("Opened company post composer", 25)

            await self._wait_for_company_composer()
            await self._fill_post_text(text)
            await self.callback.on_progress("Post text filled", 60)

            result = PublishResult(
                actor="company",
                dry_run=dry_run,
                composer_opened=True,
                text_filled=True,
                submitted=False,
                visibility=visibility,
                destination_url=admin_share_url,
                message="Company post composer is ready."
                if dry_run
                else "Company post submitted.",
            )

            if dry_run:
                await self.callback.on_complete("publish_company_post", result)
                return result

            await self._submit_post()
            result.submitted = True
            result.post_url = self.page.url
            await self.callback.on_complete("publish_company_post", result)
            return result
        except Exception as e:
            await self.callback.on_error(e)
            raise

    async def _open_person_composer(self) -> bool:
        """Try multiple strategies to open the personal post composer."""
        strategies = [
            self._open_person_composer_via_direct_route,
            self._open_person_composer_via_click,
        ]

        for strategy in strategies:
            try:
                if await strategy():
                    return True
            except Exception as e:
                logger.debug(f"Person composer strategy failed: {strategy.__name__}: {e}")

        return False

    async def _open_person_composer_via_direct_route(self) -> bool:
        await self.navigate_and_wait("https://www.linkedin.com/feed/?shareActive=true")
        await self.page.wait_for_selector("main", timeout=10000)
        await self.wait_and_focus(1)
        return await self._wait_for_editor(timeout_ms=3000)

    async def _open_person_composer_via_click(self) -> bool:
        await self.navigate_and_wait("https://www.linkedin.com/feed/")
        await self.page.wait_for_selector("main", timeout=10000)
        await self.wait_and_focus(1)

        locators = [
            self.page.locator('[aria-label="Start a post"]').first,
            self.page.get_by_text("Start a post", exact=True).first,
            self.page.locator("p").filter(has_text="Start a post").first,
        ]

        for locator in locators:
            if await locator.count() == 0:
                continue
            try:
                await locator.click(timeout=3000)
                await self.wait_and_focus(1)
            except Exception:
                try:
                    await locator.evaluate("(el) => el.click()")
                    await self.wait_and_focus(1)
                except Exception:
                    continue

            if await self._wait_for_editor(timeout_ms=2500):
                return True

        return False

    async def _wait_for_company_composer(self) -> None:
        """Wait until the company composer is visible."""
        candidates = [
            '[aria-label="Text editor for creating content"]',
            'div[contenteditable="true"]',
        ]
        for selector in candidates:
            locator = self.page.locator(selector).first
            if await locator.count() == 0:
                continue
            try:
                await locator.wait_for(state="visible", timeout=5000)
                return
            except Exception:
                continue
        raise ScrapingError("Company composer editor was not found.")

    async def _wait_for_person_composer(self) -> None:
        """Wait until the personal composer is truly visible."""
        for selector in [
            'text="What do you want to talk about?"',
            '[aria-label="Text editor for creating content"]',
        ]:
            locator = self.page.locator(selector).first
            if await locator.count() == 0:
                continue
            try:
                await locator.wait_for(state="visible", timeout=4000)
                return
            except Exception:
                continue
        raise ScrapingError("Personal post composer did not become visible.")

    async def _wait_for_editor(self, timeout_ms: int = 5000) -> bool:
        """Wait for any visible composer editor."""
        candidates = [
            '[aria-label="Text editor for creating content"]',
            'div[contenteditable="true"]',
            'textarea[placeholder]',
        ]
        for selector in candidates:
            locator = self.page.locator(selector).first
            if await locator.count() == 0:
                continue
            try:
                await locator.wait_for(state="visible", timeout=timeout_ms)
                return True
            except Exception:
                continue
        return False

    async def _fill_post_text(self, text: str) -> None:
        """Focus the composer and type post text."""
        editor = await self._get_primary_editor()
        await editor.click()
        await self.wait_and_focus(0.5)
        await self.page.keyboard.type(text, delay=10)
        await self.wait_and_focus(0.5)
        if not await self._editor_contains_text(text):
            raise ScrapingError("Post text was not inserted into the composer.")

    async def _editor_contains_text(self, text: str) -> bool:
        """Verify that at least one visible editor contains the typed text."""
        snippet = text.strip()
        if not snippet:
            return False

        script = """
        (target) => {
            const nodes = Array.from(document.querySelectorAll('[contenteditable="true"], textarea'));
            return nodes.some((el) => {
                const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                const value = (el.innerText || el.textContent || el.value || '').trim();
                return visible && value.includes(target);
            });
        }
        """
        try:
            return await self.page.evaluate(script, snippet)
        except Exception:
            return False

    async def _get_primary_editor(self):
        candidates = [
            self.page.locator('[aria-label="Text editor for creating content"]').first,
            self.page.locator('div[contenteditable="true"]').first,
            self.page.locator("textarea").first,
        ]
        for locator in candidates:
            if await locator.count() == 0:
                continue
            try:
                await locator.wait_for(state="visible", timeout=5000)
                return locator
            except Exception:
                continue
        raise ScrapingError("Could not find the post editor.")

    async def _submit_post(self) -> None:
        """Click the final Post button."""
        button = self.page.get_by_text("Post", exact=True).first
        if await button.count() == 0:
            raise ScrapingError("Could not find the final Post button.")
        await button.click(timeout=5000)
        await self.wait_and_focus(2)

    async def _dismiss_generic_modals(self) -> None:
        """Close intercepting premium or upsell modals when present."""
        dismiss = self.page.locator('[aria-label="Dismiss"]').first
        if await dismiss.count() > 0:
            try:
                await dismiss.click(timeout=2000)
                await self.wait_and_focus(1)
            except Exception:
                pass

    def _build_company_share_url(self, company_url: str) -> str:
        """Convert company page URL into a direct admin share URL."""
        normalized = company_url.rstrip("/")
        if "/admin/page-posts/published" in normalized:
            if "share=true" in normalized:
                return normalized
            return normalized + ("&share=true" if "?" in normalized else "?share=true")
        return normalized + "/admin/page-posts/published/?share=true"
