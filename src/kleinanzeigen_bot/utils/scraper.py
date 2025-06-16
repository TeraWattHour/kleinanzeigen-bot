# SPDX-FileCopyrightText: © Sebastian Thomschke and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-ArtifactOfProjectHomePage: https://github.com/Second-Hand-Friends/kleinanzeigen-bot/
import asyncio, enum, inspect, json, os, platform, secrets, shutil  # isort: skip
from collections.abc import Callable, Coroutine, Iterable
from gettext import gettext as _
from typing import Any, Final, Optional, cast

from typing import Never

import nodriver
from nodriver.core.browser import Browser
from nodriver.core.config import Config
from nodriver.core.element import Element
from nodriver.core.tab import Tab as Page

from . import net
from .misc import T, ainput, ensure

__all__ = [
    "Browser",
    "By",
    "Element",
    "Page",
    "Is",
    "Scraper",
]


# see https://api.jquery.com/category/selectors/
METACHAR_ESCAPER: Final[dict[int, str]] = str.maketrans({ch: f"\\{ch}" for ch in '!"#$%&\'()*+,./:;<=>?@[\\]^`{|}~'})


class By(enum.Enum):
    ID = enum.auto()
    CLASS_NAME = enum.auto()
    CSS_SELECTOR = enum.auto()
    TAG_NAME = enum.auto()
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

    async def check_logged_in(self, username: str):
        try:
            user_info = await self.web_text(By.CLASS_NAME, "mr-medium")
            if username.lower() in user_info.lower():
                return True
        except TimeoutError:
            try:
                user_info = await self.web_text(By.ID, "user-email")
                if username.lower() in user_info.lower():
                    return True
            except TimeoutError:
                return False
        return False
    
    async def ensure_logged_in(self, username: str):
        assert await self.check_logged_in(username), "Log in before starting the program"
        
    async def detect_captcha(self) -> None:
        try:
            await self.web_find(By.CSS_SELECTOR,
                                "iframe[name^='a-'][src^='https://www.google.com/recaptcha/api2/anchor?']", timeout = 2)

            print("############################################")
            print("# Captcha present! Please solve the captcha.")
            print("############################################")

            await self.web_scroll_page_down()

            await ainput(_("Press a key to continue..."))
        except TimeoutError:
            pass

    async def web_await(self, condition:Callable[[], T | Never | Coroutine[Any, Any, T | Never]], *,
            timeout:int | float = 5, timeout_error_message:str = "") -> T:
        """
        Blocks/waits until the given condition is met.

        :param timeout: timeout in seconds
        :raises TimeoutError: if element could not be found within time
        """
        loop = asyncio.get_running_loop()
        start_at = loop.time()

        while True:
            await self.page
            ex: Optional[Exception] = None
            try:
                result_raw = condition()
                result: T = cast(T, await result_raw if inspect.isawaitable(result_raw) else result_raw)
                if result:
                    return result
            except Exception as ex1:
                ex = ex1
            if loop.time() - start_at > timeout:
                if ex:
                    raise ex
                raise TimeoutError(timeout_error_message or f"Condition not met within {timeout} seconds")
            await self.page.sleep(0.5)

    async def web_check(self, selector_type: By, selector_value: str, attr: Is, *, timeout: int | float = 5) -> bool:
        """
        Locates an HTML element and returns a state.

        :param timeout: timeout in seconds
        :raises TimeoutError: if element could not be found within time
        """

        def is_disabled(elem: Element) -> bool:
            return elem.attrs.get("disabled") is not None

        async def is_displayed(elem: Element) -> bool:
            return cast(bool, await elem.apply("""
                function (element) {
                    var style = window.getComputedStyle(element);
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.opacity !== '0'
                        && element.offsetWidth > 0
                        && element.offsetHeight > 0
                }
            """))

        elem: Element = await self.web_find(selector_type, selector_value, timeout = timeout)

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
                    function (element) {
                        if (element.tagName.toLowerCase() === 'input') {
                            if (element.type === 'checkbox' || element.type === 'radio') {
                                return element.checked
                            }
                        }
                        return false
                    }
                """))
        raise AssertionError(_("Unsupported attribute: %s") % attr)

    async def web_click(self, selector_type:By, selector_value:str, *, timeout:int | float = 5) -> Element:
        """
        Locates an HTML element by ID.

        :param timeout: timeout in seconds
        :raises TimeoutError: if element could not be found within time
        """
        elem = await self.web_find(selector_type, selector_value, timeout = timeout)
        await elem.click()
        await self.web_sleep()
        return elem

    async def web_execute(self, jscode:str) -> Any:
        """
        Executes the given JavaScript code in the context of the current page.

        :return: The javascript's return value
        """
        result = await self.page.evaluate(jscode, await_promise = True, return_by_value = True)

        # debug log the jscode but avoid excessive debug logging of window.scrollTo calls
        _prev_jscode:str = getattr(self.__class__.web_execute, "_prev_jscode", "")
        if not (jscode == _prev_jscode or (jscode.startswith("window.scrollTo") and _prev_jscode.startswith("window.scrollTo"))):
            print("web_execute(`%s`) = `%s`", jscode, result)
        self.__class__.web_execute._prev_jscode = jscode  # type: ignore[attr-defined]  # noqa: SLF001 Private member accessed

        return result

    async def web_find(self, selector_type:By, selector_value:str, *, parent:Element | None = None, timeout:int | float = 5) -> Element:
        """
        Locates an HTML element by the given selector type and value.

        :param timeout: timeout in seconds
        :raises TimeoutError: if element could not be found within time
        """
        match selector_type:
            case By.ID:
                escaped_id = selector_value.translate(METACHAR_ESCAPER)
                return await self.web_await(
                    lambda: self.page.query_selector(f"#{escaped_id}", parent),
                    timeout = timeout,
                    timeout_error_message = f"No HTML element found with ID '{selector_value}' within {timeout} seconds.") # type: ignore
            case By.CLASS_NAME:
                escaped_classname = selector_value.translate(METACHAR_ESCAPER)
                return await self.web_await(
                    lambda: self.page.query_selector(f".{escaped_classname}", parent),
                    timeout = timeout,
                    timeout_error_message = f"No HTML element found with CSS class '{selector_value}' within {timeout} seconds.") # type: ignore
            case By.TAG_NAME:
                return await self.web_await(
                    lambda: self.page.query_selector(selector_value, parent),
                    timeout = timeout,
                    timeout_error_message = f"No HTML element found of tag <{selector_value}> within {timeout} seconds.") # type: ignore
            case By.CSS_SELECTOR:
                return await self.web_await(
                    lambda: self.page.query_selector(selector_value, parent),
                    timeout = timeout,
                    timeout_error_message = f"No HTML element found using CSS selector '{selector_value}' within {timeout} seconds.") # type: ignore
            case By.TEXT:
                ensure(not parent, f"Specifying a parent element currently not supported with selector type: {selector_type}")
                return await self.web_await(
                    lambda: self.page.find_element_by_text(selector_value, best_match = True),
                    timeout = timeout,
                    timeout_error_message = f"No HTML element found containing text '{selector_value}' within {timeout} seconds.") # type: ignore
            case By.XPATH:
                ensure(not parent, f"Specifying a parent element currently not supported with selector type: {selector_type}")
                return await self.web_await(
                    lambda: self.page.find_element_by_text(selector_value, best_match = True),
                    timeout = timeout,
                    timeout_error_message = f"No HTML element found using XPath '{selector_value}' within {timeout} seconds.") # type: ignore

        raise AssertionError(_("Unsupported selector type: %s") % selector_type)

    async def web_find_all(self, selector_type:By, selector_value:str, *, parent:Element | None = None, timeout:int | float = 5) -> list[Element]:
        """
        Locates an HTML element by ID.

        :param timeout: timeout in seconds
        :raises TimeoutError: if element could not be found within time
        """
        match selector_type:
            case By.CLASS_NAME:
                escaped_classname = selector_value.translate(METACHAR_ESCAPER)
                return await self.web_await(
                    lambda: self.page.query_selector_all(f".{escaped_classname}", parent),
                    timeout = timeout,
                    timeout_error_message = f"No HTML elements found with CSS class '{selector_value}' within {timeout} seconds.")
            case By.CSS_SELECTOR:
                return await self.web_await(
                    lambda: self.page.query_selector_all(selector_value, parent),
                    timeout = timeout,
                    timeout_error_message = f"No HTML elements found using CSS selector '{selector_value}' within {timeout} seconds.")
            case By.TAG_NAME:
                return await self.web_await(
                    lambda: self.page.query_selector_all(selector_value, parent),
                    timeout = timeout,
                    timeout_error_message = f"No HTML elements found of tag <{selector_value}> within {timeout} seconds.")
            case By.TEXT:
                ensure(not parent, f"Specifying a parent element currently not supported with selector type: {selector_type}")
                return await self.web_await(
                    lambda: self.page.find_elements_by_text(selector_value),
                    timeout = timeout,
                    timeout_error_message = f"No HTML elements found containing text '{selector_value}' within {timeout} seconds.")
            case By.XPATH:
                ensure(not parent, f"Specifying a parent element currently not supported with selector type: {selector_type}")
                return await self.web_await(
                    lambda: self.page.find_elements_by_text(selector_value),
                    timeout = timeout,
                    timeout_error_message = f"No HTML elements found using XPath '{selector_value}' within {timeout} seconds.")

        raise AssertionError(_("Unsupported selector type: %s") % selector_type)

    async def web_input(self, selector_type:By, selector_value:str, text:str | int, *, timeout:int | float = 5) -> Element:
        """
        Enters text into an HTML input field.

        :param timeout: timeout in seconds
        :raises TimeoutError: if element could not be found within time
        """
        input_field = await self.web_find(selector_type, selector_value, timeout = timeout)
        await input_field.clear_input()
        await input_field.send_keys(str(text))
        await self.web_sleep()
        return input_field

    async def web_text(self, selector_type:By, selector_value:str, *, parent:Element | None = None, timeout:int | float = 5) -> str:
        return str(await (await self.web_find(selector_type, selector_value, parent = parent, timeout = timeout)).apply("""
            function (elem) {
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

    async def web_sleep(self, min_ms:int = 1_000, max_ms:int = 2_500) -> None:
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
        print(script)
        response = cast(dict[str, Any], await self.page.evaluate(script, await_promise = True, return_by_value = True))
        print(response)
        ensure(
            response["statusCode"] in valid_response_codes,
            f'Invalid response "{response["statusCode"]} response["statusMessage"]" received for HTTP {method} to {url}'
        )

        return response["data"]
    # pylint: enable=dangerous-default-value

    async def web_scroll_page_down(self, scroll_length:int = 10, scroll_speed:int = 10_000, *, scroll_back_top:bool = False) -> None:
        """
        Smoothly scrolls the current web page down.

        :param scroll_length: the length of a single scroll iteration, determines smoothness of scrolling, lower is smoother
        :param scroll_speed: the speed of scrolling, higher is faster
        :param scroll_back_top: whether to scroll the page back to the top after scrolling to the bottom
        """
        current_y_pos = 0
        bottom_y_pos:int = await self.web_execute("document.body.scrollHeight")  # get bottom position
        while current_y_pos < bottom_y_pos:  # scroll in steps until bottom reached
            current_y_pos += scroll_length
            await self.web_execute(f"window.scrollTo(0, {current_y_pos})")  # scroll one step
            await asyncio.sleep(scroll_length / scroll_speed)

        if scroll_back_top:  # scroll back to top in same style
            while current_y_pos > 0:
                current_y_pos -= scroll_length
                await self.web_execute(f"window.scrollTo(0, {current_y_pos})")
                await asyncio.sleep(scroll_length / scroll_speed / 2)  # double speed

    async def web_select(self, selector_type:By, selector_value:str, selected_value:Any, timeout:int | float = 5) -> Element:
        """
        Selects an <option/> of a <select/> HTML element.

        :param timeout: timeout in seconds
        :raises TimeoutError: if element could not be found within time
        :raises UnexpectedTagNameException: if element is not a <select> element
        """
        await self.web_await(
            lambda: self.web_check(selector_type, selector_value, Is.CLICKABLE), timeout = timeout,
            timeout_error_message = f"No clickable HTML element with selector: {selector_type}='{selector_value}' found"
        )
        elem = await self.web_find(selector_type, selector_value)
        await elem.apply(f"""
            function (element) {{
              for(let i=0; i < element.options.length; i++)
                {{
                  if(element.options[i].value == "{selected_value}") {{
                    element.selectedIndex = i;
                    element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    break;
                }}
              }}
              throw new Error("Option with value {selected_value} not found.");
            }}
        """)
        await self.web_sleep()
        return elem
