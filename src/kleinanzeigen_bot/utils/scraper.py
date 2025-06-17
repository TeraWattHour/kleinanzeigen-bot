# SPDX-FileCopyrightText: © Sebastian Thomschke and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-ArtifactOfProjectHomePage: https://github.com/Second-Hand-Friends/kleinanzeigen-bot/
import asyncio, enum, secrets
from collections.abc import Callable, Iterable
from gettext import gettext as _
from types import CoroutineType
from typing import Any, Final, TypeVar, Union, cast

import nodriver
from nodriver.core.browser import Browser
from nodriver.core.config import Config
from nodriver.core.element import Element
from nodriver.core.tab import Tab as Page

from . import net
from .misc import ainput, ensure

__all__ = [
    "Browser",
    "By",
    "Element",
    "Page",
    "Is",
    "Scraper",
]


T = TypeVar("T", bound=object)
type Timeout = int | float

class By(enum.Enum):
    CSS_SELECTOR = enum.auto()
    TEXT = enum.auto()
    XPATH = enum.auto()

class Is(enum.Enum):
    CLICKABLE = enum.auto()
    DISPLAYED = enum.auto()
    DISABLED = enum.auto()
    READONLY = enum.auto()
    SELECTED = enum.auto()

async def create_browser_session(browser_socket: str) -> Browser:
    remote_host, remote_port = browser_socket.split(":")
    remote_port = int(remote_port) if remote_port else 0
    assert remote_host, "Malformed `browser_socket` configuration, expected format: 'host:port'"
    assert net.is_port_open(remote_host, remote_port), f"Browser remote debugging port is not open on socket {browser_socket}"

    return await nodriver.start(Config(host=remote_host, port=remote_port))

class Scraper:
    def __init__(self, page: nodriver.Tab) -> None:
        self.page = page

    async def goto(self, url: str):
        self.page = await self.page.get(url)

    async def check_logged_in(self, username: str):
        try:
            user_info = await self.get_inner_text(By.CSS_SELECTOR, ".mr-medium")
            if username.lower() in user_info.lower():
                return True
        except TimeoutError:
            try:
                user_info = await self.get_inner_text(By.CSS_SELECTOR, "#user-email")
                if username.lower() in user_info.lower():
                    return True
            except TimeoutError:
                return False
        return False
    
    async def ensure_logged_in(self, username: str):
        assert await self.check_logged_in(username), "Log in before starting the program"
        
    async def detect_captcha(self) -> None:
        try:
            captcha = await self.query(By.CSS_SELECTOR, "iframe[name^='a-'][src^='https://www.google.com/recaptcha/api2/anchor?']", timeout = 2)
            await captcha.scroll_into_view()

            print("############################################")
            print("# Captcha present! Please solve the captcha.")
            print("############################################")

            await ainput(_("Press a key to continue..."))
        except TimeoutError:
            pass

    async def wait_for(
        self, 
        condition: Union[
            Callable[[], Union[T, None]],
            CoroutineType[Any, Any, Union[T, None]]
        ], 
        timeout: int | float = 5,
        timeout_msg: str = "timed out"
    ) -> T:
        async def _poll() -> T:
            while True:
                if asyncio.iscoroutine(condition):
                    result = await condition
                else:
                    result = condition()

                if result is not None and result:
                    return result # type: ignore
                
                await asyncio.sleep(0.05)

        try:
            return await asyncio.wait_for(_poll(), timeout=timeout)
        except TimeoutError:
            raise TimeoutError(timeout_msg)

    async def web_check(self, by: By, selector: str, attr: Is, *, timeout: Timeout = 5) -> bool:
        def is_disabled(elem: Element) -> bool:
            return elem.attrs.get("disabled") is not None

        async def is_displayed(elem: Element) -> bool:
            return cast(bool, await elem.apply("""
                (element) => {
                    var style = window.getComputedStyle(element);
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.opacity !== '0'
                        && element.offsetWidth > 0
                        && element.offsetHeight > 0
                }
            """))

        elem = await self.query(by, selector, timeout=timeout)

        match attr:
            case Is.CLICKABLE:
                return not is_disabled(elem) or await is_displayed(elem)
            case Is.DISPLAYED:
                return await is_displayed(elem)
            case Is.DISABLED:
                return is_disabled(elem)
            case Is.READONLY:
                return elem.attrs.get("readonly") is not None
            case Is.SELECTED:
                return cast(bool, await elem.apply("""
                    (element) => {
                        if (element.tagName.toLowerCase() === 'input') {
                            if (element.type === 'checkbox' || element.type === 'radio') {
                                return element.checked
                            }
                        }
                        return false
                    }
                """))
        raise AssertionError(_("Unsupported attribute: %s") % attr)

    async def click(self, by: By, selector: str, *, timeout: Timeout = 5) -> Element:
        elem = await self.query(by, selector, timeout=timeout)
        await elem.click()
        await self.sleep(50, 200)
        return elem

    async def script(self, code: str) -> Any:
        return await self.page.evaluate(code, await_promise=True, return_by_value=True)
    
    async def query(self, by: By, selector: str, parent: Element | None = None, *, timeout: Timeout = 5) -> Element:
        closure: CoroutineType[Any, Any, Union[Element, None]]
        match by:
            case By.CSS_SELECTOR: closure = self.page.query_selector(selector, parent) # type: ignore
            case By.XPATH, By.TEXT: closure = self.page.find_element_by_text(selector, best_match=True) # type: ignore
            case _: raise Exception("unreachable; unknown selector")

        return await self.wait_for(closure, timeout, timeout_msg=f"couldn't find anything matching `{selector}`")

    async def query_all(self, selector_type:By, selector:str, *, parent:Element | None = None, timeout: Timeout = 5) -> list[Element]:
        closure: CoroutineType[Any, Any, list[Element]]
        match selector_type:
            case By.CSS_SELECTOR: closure = self.page.query_selector_all(selector, parent)
            case By.XPATH, By.TEXT: closure = self.page.find_elements_by_text(selector, best_match=True)
            case _: raise Exception("unreachable; unknown selector")

        return await self.wait_for(closure, timeout)
    
    async def input(self, by: By, selector: str, text: str | int, *, timeout: Timeout = 5) -> Element:
        input_field = await self.query(by, selector, timeout=timeout)
        await input_field.clear_input()
        await input_field.send_keys(str(text))
        await self.sleep()
        return input_field

    async def get_inner_text(self, by: By, selector: str, parent: Element | None = None, *, timeout: Timeout = 5) -> str:
        return str(await (await self.query(by, selector, parent, timeout=timeout)).apply("""
            (elem) => {
                let sel = window.getSelection()
                sel.removeAllRanges()
                let range = document.createRange()
                range.selectNode(elem)
                sel.addRange(range)
                let visibleText = sel.toString().trim()
                sel.removeAllRanges()
                return visibleText
            }
        """))

    async def sleep(self, min_ms:int = 1_000, max_ms:int = 2_500) -> None:
        duration = max_ms <= min_ms and min_ms or secrets.randbelow(max_ms - min_ms) + min_ms
        print("sleeping")
        # LOG.log(loggers.INFO if duration > 1_500 else loggers.DEBUG,  # noqa: PLR2004 Magic value used in comparison
        #         " ... pausing for %d ms ...", duration)
        await self.page.sleep(duration / 1_000)

    async def fetch(self, url: str, method: str = "GET", valid_response_codes: int | Iterable[int] = 200) -> Any:
        valid_response_codes = [valid_response_codes] if isinstance(valid_response_codes, int) else valid_response_codes
        
        script = f"""
            fetch("{url}", {{
                method: "{method}",
                redirect: "follow"
            }})
            .then(response => response.json().then(data => {{ return {{ statusCode: response.status, data }} }}))
        """
        response = cast(dict[str, Any], await self.page.evaluate(script, await_promise = True, return_by_value = True))
        ensure(
            response["statusCode"] in valid_response_codes,
            f'Invalid response "{response["statusCode"]} response["statusMessage"]" received for HTTP {method} to {url}'
        )

        return response["data"]

    async def web_select(self, by: By, selector: str, selected_value:Any, *, timeout:Timeout = 5) -> Element:
        """
        Selects an <option/> of a <select/> HTML element.

        :param timeout: timeout in seconds
        :raises TimeoutError: if element could not be found within time
        :raises UnexpectedTagNameException: if element is not a <select> element
        """
        await self.wait_for(lambda: self.web_check(by, selector, Is.CLICKABLE), timeout=timeout)
        elem = await self.query(by, selector)
        await elem.apply(f"""
            (element) => {{
                for(let i=0; i < element.options.length; i++) {{
                    if(element.options[i].value == "{selected_value}") {{
                        element.selectedIndex = i;
                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        break;
                    }}
                }}
                throw new Error("Option with value {selected_value} not found.");
            }}
        """)
        await self.sleep()
        return elem
