"""LinkedIn post publishing helpers built on top of the Playwright session."""

import asyncio
import logging
import re
from typing import Optional

from .base import BaseScraper
from ..models import PublishResult
from ..callbacks import ProgressCallback, SilentCallback
from ..core.exceptions import ScrapingError

logger = logging.getLogger(__name__)


class PostPublisher(BaseScraper):
    """Browser automation for personal and company LinkedIn posts."""

    MENTION_PATTERN = re.compile(r"@([A-Za-z0-9][A-Za-z0-9._-]{1,79})")

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
            mention_inserted = await self._fill_post_text(text)
            await self.callback.on_progress("Post text filled", 65)

            result = PublishResult(
                actor="person",
                dry_run=dry_run,
                composer_opened=True,
                text_filled=True,
                mention_inserted=mention_inserted,
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

    async def publish_person_repost(
        self,
        source_post_url: str,
        text: str,
        dry_run: bool = True,
        visibility: str = "Anyone",
        identity_name: str = "Anton Nazarov",
    ) -> PublishResult:
        """Native repost with commentary from a member profile."""
        await self.callback.on_start("publish_person_repost", source_post_url)

        try:
            await self.navigate_and_wait(self._normalize_post_url(source_post_url))
            await self.ensure_logged_in()
            await self.page.wait_for_selector("body", timeout=10000)
            await self.wait_and_focus(1)

            await self._switch_interaction_identity(identity_name)
            dialog = await self._open_repost_with_thoughts()
            await self.callback.on_progress("Native repost composer opened", 35)

            mention_inserted = await self._fill_post_text(text, container=dialog)
            await self.callback.on_progress("Repost commentary filled", 65)

            result = PublishResult(
                actor="person-repost",
                dry_run=dry_run,
                composer_opened=True,
                text_filled=True,
                mention_inserted=mention_inserted,
                submitted=False,
                visibility=visibility,
                destination_url=self.page.url,
                source_post_url=source_post_url,
                message="Native repost composer is ready."
                if dry_run
                else "Native repost submitted.",
            )

            if dry_run:
                await self.callback.on_complete("publish_person_repost", result)
                return result

            await self._submit_post(container=dialog)
            result.submitted = True
            await self.wait_and_focus(3)
            result.post_url = (
                await self._extract_repost_post_url(text, source_post_url)
                or self.page.url
            )
            await self.callback.on_complete("publish_person_repost", result)
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
            dialog = await self._wait_for_company_composer()
            await self.callback.on_progress("Opened company post composer", 25)
            mention_inserted = await self._fill_post_text(text, container=dialog)
            await self.callback.on_progress("Post text filled", 60)

            result = PublishResult(
                actor="company",
                dry_run=dry_run,
                composer_opened=True,
                text_filled=True,
                mention_inserted=mention_inserted,
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

            await self._submit_post(container=dialog)
            result.submitted = True
            await self.wait_and_focus(4)
            result.post_url = await self._extract_latest_post_url() or self.page.url
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

    async def _wait_for_company_composer(self):
        """Wait until the company create-post modal is visible and return it."""
        dialog = self.page.locator('[role="dialog"]').filter(has_text="Create post modal").first
        if await dialog.count() > 0:
            try:
                await dialog.wait_for(state="visible", timeout=8000)
                editor = dialog.locator('[aria-label="Text editor for creating content"]').first
                await editor.wait_for(state="visible", timeout=5000)
                return dialog
            except Exception:
                pass
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

    async def _open_repost_with_thoughts(self):
        repost_button = self.page.get_by_text("Repost", exact=True).first
        if await repost_button.count() == 0:
            raise ScrapingError("Could not find the Repost button.")
        await repost_button.click(timeout=5000)
        await self.wait_and_focus(1)

        repost_with_thoughts = self.page.get_by_text("Repost with your thoughts", exact=True).first
        if await repost_with_thoughts.count() == 0:
            raise ScrapingError("Could not find the native repost action.")
        await repost_with_thoughts.click(timeout=5000)
        await self.wait_and_focus(2)

        dialog = self.page.locator('[role="dialog"]').filter(has_text="Create post modal").first
        await dialog.wait_for(state="visible", timeout=8000)
        editor = dialog.locator('[contenteditable="true"], [aria-label="Text editor for creating content"]').first
        await editor.wait_for(state="visible", timeout=5000)
        return dialog

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

    async def _fill_post_text(self, text: str, container=None) -> bool:
        """Focus the composer and type post text, preserving supported @mentions."""
        editor = await self._get_primary_editor(container=container)
        mention_inserted = False
        mentions = list(self.MENTION_PATTERN.finditer(text))

        if mentions:
            mention_inserted = await self._type_text_with_mentions(editor, text, mentions, container=container)
        else:
            try:
                await editor.click()
                await self.wait_and_focus(0.5)
                await self.page.keyboard.type(text, delay=10)
                await self.wait_and_focus(0.5)
            except Exception:
                logger.debug("Keyboard typing failed, will try DOM insertion")

            if not await self._editor_contains_text(text, container=container):
                await self._set_editor_text_via_dom(editor, text)
                await self.wait_and_focus(0.5)

        if not await self._editor_contains_text(self._plain_text_for_validation(text), container=container):
            raise ScrapingError("Post text was not inserted into the composer.")
        return mention_inserted

    async def _type_text_with_mentions(self, editor, text: str, mentions, container=None) -> bool:
        """Type text as: prefix -> mention -> suffix, preserving contextual placement."""
        await editor.click()
        await self.wait_and_focus(0.5)
        await self._clear_editor(editor)

        mention_inserted = False
        for prefix, mention_name, suffix in self._split_text_around_mentions(text, mentions):
            if prefix:
                await self.page.keyboard.type(prefix, delay=10)
                await self.wait_and_focus(0.2)

            inserted = await self._insert_company_mention(mention_name)
            mention_inserted = mention_inserted or inserted
            if not inserted:
                await self._remove_partial_mention_token(editor, mention_name)
                await self.page.keyboard.type("@" + mention_name, delay=10)
                await self.wait_and_focus(0.2)

            if suffix:
                await self.page.keyboard.type(suffix, delay=10)
                await self.wait_and_focus(0.3)

        if not await self._editor_contains_text(self._plain_text_for_validation(text), container=container):
            if mention_inserted:
                raise ScrapingError("Mention was inserted, but the final text did not validate cleanly.")
            await self._set_editor_text_via_dom(editor, text)
            await self.wait_and_focus(0.5)
        return mention_inserted

    def _split_text_around_mentions(self, text: str, mentions):
        """
        Yield segments as:
        - text before current mention
        - mention name without '@'
        - text after current mention until the next mention or end of string
        """
        for index, match in enumerate(mentions):
            prefix_start = 0 if index == 0 else mentions[index - 1].end()
            suffix_end = len(text) if index + 1 >= len(mentions) else mentions[index + 1].start()
            prefix = text[prefix_start:match.start()]
            mention_name = match.group(1).strip()
            suffix = text[match.end():suffix_end]
            yield prefix, mention_name, suffix

    async def _insert_company_mention(self, mention_name: str) -> bool:
        """Insert a LinkedIn @mention by selecting the typeahead option."""
        await self.page.keyboard.type(f"@{mention_name}", delay=30)
        await self.wait_and_focus(1.5)

        option = self.page.locator('[role="option"]').filter(has_text=mention_name).first
        if await option.count() == 0:
            return False
        try:
            await option.click(force=True, timeout=3000)
            await self.wait_and_focus(0.8)
        except Exception:
            try:
                await self.page.keyboard.press("ArrowDown")
                await self.wait_and_focus(0.2)
                await self.page.keyboard.press("Enter")
                await self.wait_and_focus(0.8)
            except Exception:
                return False

        return await self._editor_has_entity_mention(mention_name)

    async def _editor_contains_text(self, text: str, container=None) -> bool:
        """Verify that at least one visible editor contains the typed text."""
        snippet = text.strip()
        if not snippet:
            return False

        script = """
        ({target, rootSelector}) => {
            const normalize = (value) =>
                (value || '')
                    .replace(/\\u00a0/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim()
                    .toLowerCase();
            const root = rootSelector ? document.querySelector(rootSelector) : document;
            if (!root) return false;
            const nodes = Array.from(root.querySelectorAll('[contenteditable="true"], textarea'));
            const wanted = normalize(target);
            return nodes.some((el) => {
                const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                const value = normalize(el.innerText || el.textContent || el.value || '');
                return visible && value.includes(wanted);
            });
        }
        """
        try:
            root_selector = None
            if container is not None:
                root_selector = '[role="dialog"]'
            return await self.page.evaluate(script, {"target": snippet, "rootSelector": root_selector})
        except Exception:
            return False

    async def _set_editor_text_via_dom(self, editor, text: str) -> None:
        """Fallback for LinkedIn editors that ignore normal keyboard typing."""
        await editor.evaluate(
            """
            (el, value) => {
                el.focus();
                el.innerHTML = '';
                el.textContent = value;
                el.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    inputType: 'insertText',
                    data: value,
                }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
            """,
            text,
        )

    async def _clear_editor(self, editor) -> None:
        try:
            await editor.evaluate(
                """
                (el) => {
                    el.focus();
                    el.innerHTML = '';
                    el.textContent = '';
                    el.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        inputType: 'deleteContentBackward',
                    }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """
            )
        except Exception:
            pass

    async def _editor_has_entity_mention(self, mention_name: str) -> bool:
        """Check whether the editor contains a real LinkedIn mention entity, not plain text."""
        script = """
        (target) => {
            const nodes = Array.from(document.querySelectorAll(
                'a.ql-mention, [data-test-ql-mention=\"true\"]'
            ));
            return nodes.some((el) => {
                const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                const original = (el.getAttribute('data-original-text') || '').trim().toLowerCase();
                return text === target || original === target;
            });
        }
        """
        try:
            return await self.page.evaluate(script, mention_name.strip().lower())
        except Exception:
            return False

    async def _remove_partial_mention_token(self, editor, mention_name: str) -> None:
        """Remove a failed raw @mention token before falling back to plain text."""
        token = f"@{mention_name}"
        try:
            await editor.evaluate(
                """
                (el, rawToken) => {
                    const text = (el.innerText || el.textContent || '');
                    if (!text.endsWith(rawToken)) return;
                    const trimmed = text.slice(0, -rawToken.length);
                    el.innerHTML = '';
                    el.textContent = trimmed;
                    el.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        inputType: 'deleteContentBackward',
                    }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """,
                token,
            )
            await self.wait_and_focus(0.2)
        except Exception:
            pass

    async def _get_primary_editor(self, container=None):
        scope = container if container is not None else self.page
        candidates = [
            scope.locator('[aria-label="Text editor for creating content"]').first,
            scope.locator('div[contenteditable="true"]').first,
            scope.locator("textarea").first,
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

    async def _submit_post(self, container=None) -> None:
        """Click the final Post button."""
        scope = container if container is not None else self.page
        button = scope.get_by_text("Post", exact=True).first
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

    def _normalize_post_url(self, post_url: str) -> str:
        """Use the clean feed update URL for member-native repost flows."""
        normalized = post_url.rstrip("/")
        if "?" in normalized:
            normalized = normalized.split("?", 1)[0]
        return normalized + "/"

    def _plain_text_for_validation(self, text: str) -> str:
        return self.MENTION_PATTERN.sub(lambda m: m.group(1), text).strip()

    async def _extract_latest_post_url(self) -> Optional[str]:
        """Return the first visible LinkedIn update URL on the current page, if any."""
        try:
            hrefs = await self.page.locator('a[href*="/feed/update/"]').evaluate_all(
                "els => els.map(a => a.href).filter(Boolean)"
            )
        except Exception:
            return None

        seen = set()
        for href in hrefs:
            clean = href.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            if "/feed/update/" in clean:
                return clean
        return None

    async def _extract_repost_post_url(self, text: str, source_post_url: str) -> Optional[str]:
        """Best-effort extraction of the new personal repost URL after submission."""
        source_clean = self._normalize_post_url(source_post_url)

        direct = await self._extract_success_post_url(source_clean)
        if direct:
            return direct

        return await self._extract_recent_activity_post_url(text, source_clean)

    async def _extract_success_post_url(self, source_clean: str) -> Optional[str]:
        """Try to read a fresh post URL from the current page or success UI."""
        try:
            hrefs = await self.page.locator('a[href*="/feed/update/"]').evaluate_all(
                """
                els => els.map((a) => ({
                    href: a.href,
                    text: (a.innerText || a.textContent || '').trim()
                }))
                """
            )
        except Exception:
            return None

        seen = set()
        for item in hrefs:
            href = (item.get("href") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)
            clean = self._normalize_post_url(href)
            label = (item.get("text") or "").strip().lower()
            if clean == source_clean:
                continue
            if "/feed/update/" in clean:
                return href
        return None

    async def _extract_recent_activity_post_url(self, text: str, source_clean: str) -> Optional[str]:
        """Fallback: find the fresh repost by matching its commentary in recent activity."""
        snippet = self._plain_text_for_validation(text)
        if not snippet:
            return None

        try:
            await self.navigate_and_wait("https://www.linkedin.com/in/nazarovanton/recent-activity/all/")
            await self.page.wait_for_selector("main, body", timeout=10000)
            await self.wait_and_focus(2)
        except Exception:
            return None

        script = """
        ({snippet, sourceClean}) => {
            const normalize = (value) =>
                (value || '')
                    .replace(/\\u00a0/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim()
                    .toLowerCase();

            const wanted = normalize(snippet);
            if (!wanted) return null;

            const cards = Array.from(document.querySelectorAll('article, .feed-shared-update-v2, .occludable-update'));
            for (const card of cards) {
                const text = normalize(card.innerText || card.textContent || '');
                if (!text.includes(wanted)) continue;
                const links = Array.from(card.querySelectorAll('a[href*="/feed/update/"]'));
                for (const link of links) {
                    const href = (link.href || '').trim();
                    if (!href) continue;
                    const clean = href.split('?', 1)[0].replace(/\\/+$/, '') + '/';
                    if (clean === sourceClean) continue;
                    return href;
                }
            }
            return null;
        }
        """
        try:
            return await self.page.evaluate(script, {"snippet": snippet[:280], "sourceClean": source_clean})
        except Exception:
            return None

    async def _switch_interaction_identity(self, identity_name: str) -> None:
        """Open the identity switcher and select the desired actor if available."""
        toggle = self.page.locator(
            'button[aria-label*="switching identity"], .content-admin-identity-toggle-button'
        ).first
        if await toggle.count() == 0:
            return

        current_text = ((await toggle.inner_text()) or "").strip()
        if identity_name.lower() in current_text.lower():
            return

        await toggle.click(timeout=5000)
        await self.wait_and_focus(1)

        dialog = self.page.locator('[role="dialog"]').filter(has_text="Comment, react, and repost as").first
        if await dialog.count() == 0:
            return

        option = dialog.get_by_text(f"Select {identity_name}", exact=True).first
        if await option.count() == 0:
            option = dialog.get_by_text(identity_name, exact=True).first
        if await option.count() == 0:
            raise ScrapingError(f"Could not find identity option for {identity_name}.")

        try:
            await option.click(timeout=5000, force=True)
        except Exception:
            await option.evaluate(
                """
                (el) => {
                    const target = el.closest('button,[role="button"],[role="option"],li,div');
                    if (target) target.click();
                    else el.click();
                }
                """
            )
        await self.wait_and_focus(0.5)

        save = dialog.get_by_text("Save", exact=True).first
        if await save.count() > 0:
            try:
                if await save.is_enabled():
                    await save.click(timeout=5000)
                    await self.wait_and_focus(1.5)
                    return
            except Exception:
                pass

        dismiss = dialog.locator('[aria-label="Dismiss"]').first
        if await dismiss.count() > 0:
            try:
                await dismiss.click(timeout=3000)
                await self.wait_and_focus(1)
                return
            except Exception:
                pass

        await self.page.keyboard.press("Escape")
        await self.wait_and_focus(0.8)
