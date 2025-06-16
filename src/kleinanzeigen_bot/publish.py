import glob
import json
import os
from typing import Final
import urllib.parse

from nodriver import Browser, Element, Tab
from kleinanzeigen_bot.model.ad_model import Ad, AdPartial
from kleinanzeigen_bot.model.config_model import Config
from kleinanzeigen_bot.utils.misc import ainput, ensure
from kleinanzeigen_bot.utils.scraper import By, Is, Scraper, create_browser_session

URL: Final[str] = "https://www.kleinanzeigen.de"

async def get_all_published_ads(scraper: Scraper):
    page = 1
    ads = []
    while True:
        already_published = await scraper.fetch(f"{URL}/m-meine-anzeigen-verwalten.json?sort=DEFAULT&pageSize=400&pageNum={page}")
        pagination = already_published['paging']
        ads.extend(already_published['ads'])
        
        if pagination['pageNum'] >= pagination['last']:
            break

        page += 1

    return ads

def load_ad(path: str) -> AdPartial:
    with open(path, 'r') as f:
        data = json.load(f)
        return AdPartial.model_validate(data)

async def publish_ads(config: Config):
    ads = [load_ad(file) for match in config.ad_files for file in glob.glob(match)]
    if len(ads) == 0:
        print("no ad files found")
        return

    browser = await create_browser_session(config.browser_socket)
    tab = await browser.get(URL)
    scraper = Scraper(tab)
    await scraper.ensure_logged_in(config.username)

    for ad in ads:
        tab = await browser.get(f"{URL}/p-anzeige-aufgeben-schritt2.html", new_tab=True)
        try:
            await publish_ad(tab, ad.to_ad(config.ad_defaults))
        except Exception as e:
            print(e)
        await tab.close()
        
    # published_ads = await get_all_published_ads(scraper)
    # published_ids = list(map(lambda ad: ad['id'], published_ads))


async def publish_ad(tab: Tab, ad: Ad):
    scraper = Scraper(tab)

    await scraper.web_input(By.ID, "postad-title", ad.title)
    
    await __set_special_attributes(scraper, ad)
    
    await scraper.web_input(By.CSS_SELECTOR, "input#post-ad-frontend-price, input#micro-frontend-price, input#pstad-price", str(ad.price))
    await scraper.web_select(By.ID, "micro-frontend-price-type", "NEGOTIABLE")
    await scraper.web_sleep()
    
    await __set_shipping(scraper, ad)

    # set description
    await scraper.web_execute("document.querySelector('#pstad-descrptn').value = `" + ad.description.replace("`", "'") + "`")
    
    await __upload_images(scraper, ad)
    await scraper.web_sleep()

    await scraper.detect_captcha()

    try:
        await scraper.web_click(By.ID, "pstad-submit")
    except TimeoutError:
        # https://github.com/Second-Hand-Friends/kleinanzeigen-bot/issues/40
        await scraper.web_click(By.XPATH, "//fieldset[@id='postad-publish']//*[contains(., 'Anzeige aufgeben')]")
        await scraper.web_click(By.ID, "imprint-guidance-submit")

    # no image question
    try:
        image_hint_xpath = '//*[contains(@class, "ModalDialog--Actions")]//button[contains(., "Ohne Bild veröffentlichen")]'
        if not ad.images and await scraper.web_check(By.XPATH, image_hint_xpath, Is.DISPLAYED):
            await scraper.web_click(By.XPATH, image_hint_xpath)
    except TimeoutError:
        pass

    await scraper.web_await(lambda: "p-anzeige-aufgeben-bestaetigung.html?adId=" in scraper.page.url, timeout = 20)

    # extract the ad id from the URL's query parameter
    current_url_query_params = urllib.parse.parse_qs(urllib.parse.urlparse(scraper.page.url).query)
    ad_id = int(current_url_query_params.get("adId", [])[0])

    # check for approval message
    try:
        approval_link_xpath = '//*[contains(@id, "not-completed")]//a[contains(@class, "to-my-ads-link")]'
        if await scraper.web_check(By.XPATH, approval_link_xpath, Is.DISPLAYED):
            await scraper.web_click(By.XPATH, approval_link_xpath)
    except TimeoutError:
        pass 

    return ad_id

async def __set_condition(scraper: Scraper, condition_value:str) -> None:
    condition_mapping = {
        "new_with_tag": "Neu mit Etikett",
        "new": "Neu",
        "like_new": "Sehr Gut",
        "ok": "Gut",
        "alright": "In Ordnung",
        "defect": "Defekt",
    }
    mapped_condition = condition_mapping.get(condition_value)

    try:
        await scraper.web_click(By.XPATH, '//*[contains(@id, "j-post-listing-frontend-conditions")]//button[contains(., "Bitte wählen")]')
    except TimeoutError:
        print("Unable to open condition dialog and select condition [%s]", condition_value)
        return

    try:
        # Click radio button
        await scraper.web_click(By.CSS_SELECTOR, f'.SingleSelectionItem--Main input[type=radio][data-testid="{mapped_condition}"]')
    except TimeoutError:
        print("Unable to select condition [%s]", condition_value)

    try:
        # Click accept button
        await scraper.web_click(By.XPATH, '//*[contains(@id, "j-post-listing-frontend-conditions")]//dialog//button[contains(., "Bestätigen")]')
    except TimeoutError as ex:
        raise TimeoutError("Unable to close condition dialog!") from ex

async def __set_category(scraper: Scraper) -> None:
    await scraper.web_click(By.ID, "pstad-descrptn")

    try:
        await scraper.web_text(By.ID, "postad-category-path", timeout=10)
    except TimeoutError:
        raise Exception("unimplemented; manual category picker")

async def __set_special_attributes(scraper: Scraper, ad_cfg: Ad) -> None:
    if not ad_cfg.special_attributes:
        return

    for special_attribute_key, special_attribute_value in ad_cfg.special_attributes.items():

        if special_attribute_key == "condition_s":
            await __set_condition(scraper, special_attribute_value)
            continue
        
        print("Setting special attribute [%s] to [%s]..." % special_attribute_key, special_attribute_value)
        try:
            # if the <select> element exists but is inside an invisible container, make the container visible
            select_container_xpath = f"//div[@class='l-row' and descendant::select[@id='{special_attribute_key}']]"
            if not await scraper.web_check(By.XPATH, select_container_xpath, Is.DISPLAYED):
                await (await scraper.web_find(By.XPATH, select_container_xpath)).apply("elem => elem.singleNodeValue.style.display = 'block'")
        except TimeoutError:
            pass  # nosec

        try:
            # finding element by name cause id are composed sometimes eg. autos.marke_s+autos.model_s for Modell by cars
            special_attr_elem = await scraper.web_find(By.XPATH, f"//*[contains(@name, '{special_attribute_key}')]")
        except TimeoutError as ex:
            print("Attribute field '%s' could not be found." % special_attribute_key)
            raise TimeoutError(f"Failed to set special attribute [{special_attribute_key}] (not found)") from ex

        try:
            elem_id = special_attr_elem.attrs.id
            if special_attr_elem.local_name == "select":
                print("Attribute field '%s' seems to be a select..." % special_attribute_key)
                await scraper.web_select(By.ID, elem_id, special_attribute_value)
            elif special_attr_elem.attrs.type == "checkbox":
                print("Attribute field '%s' seems to be a checkbox..." % special_attribute_key)
                await scraper.web_click(By.ID, elem_id)
            else:
                print("Attribute field '%s' seems to be a text input..." % special_attribute_key)
                await scraper.web_input(By.ID, elem_id, special_attribute_value)
        except TimeoutError as ex:
            print("Attribute field '%s' is not of kind radio button." % special_attribute_key)
            raise TimeoutError(f"Failed to set special attribute [{special_attribute_key}]") from ex
        print("Successfully set attribute field [%s] to [%s]..." % special_attribute_key, special_attribute_value)

        print("unimplemented; special attributes")
        
async def __set_shipping(scraper: Scraper, ad_cfg:Ad) -> None:
    if ad_cfg.shipping_type == "PICKUP":
        try:
            await scraper.web_click(By.XPATH,
                '//*[contains(@class, "ShippingPickupSelector")]//label[contains(., "Nur Abholung")]/../input[@type="radio"]')
        except TimeoutError as ex:
            print(ex)
            # LOG.debug(ex, exc_info = True)
    elif ad_cfg.shipping_options:
        await scraper.web_click(By.XPATH, '//*[contains(@class, "SubSection")]//button[contains(@class, "SelectionButton")]')
        await scraper.web_click(By.XPATH, '//*[contains(@class, "CarrierSelectionModal")]//button[contains(., "Andere Versandmethoden")]')
        await __set_shipping_options(scraper, ad_cfg)
    else:
        special_shipping_selector = '//select[contains(@id, ".versand_s")]'
        if await scraper.web_check(By.XPATH, special_shipping_selector, Is.DISPLAYED):
            # try to set special attribute selector (then we have a commercial account)
            shipping_value = "ja" if ad_cfg.shipping_type == "SHIPPING" else "nein"
            await scraper.web_select(By.XPATH, special_shipping_selector, shipping_value)
        else:
            try:
                # no options. only costs. Set custom shipping cost
                if ad_cfg.shipping_costs is not None:
                    await scraper.web_click(By.XPATH, '//*[contains(@class, "SubSection")]//button[contains(@class, "SelectionButton")]')
                    await scraper.web_click(By.XPATH, '//*[contains(@class, "CarrierSelectionModal")]//button[contains(., "Andere Versandmethoden")]')
                    await scraper.web_click(By.XPATH, '//*[contains(@id, "INDIVIDUAL") and contains(@data-testid, "Individueller Versand")]')
                    await scraper.web_input(By.CSS_SELECTOR, '.IndividualShippingInput input[type="text"]', str.replace(str(ad_cfg.shipping_costs), ".", ","))
                    await scraper.web_click(By.XPATH, '//dialog//button[contains(., "Fertig")]')
            except TimeoutError as ex:
                raise TimeoutError("Unable to close shipping dialog!") from ex

async def __set_shipping_options(scraper: Scraper, ad_cfg:Ad) -> None:
    if not ad_cfg.shipping_options:
        return

    shipping_options_mapping = {
        "DHL_2": ("Klein", "Paket 2 kg"),
        "Hermes_Päckchen": ("Klein", "Päckchen"),
        "Hermes_S": ("Klein", "S-Paket"),
        "DHL_5": ("Mittel", "Paket 5 kg"),
        "Hermes_M": ("Mittel", "M-Paket"),
        "DHL_10": ("Groß", "Paket 10 kg"),
        "DHL_20": ("Groß", "Paket 20 kg"),
        "DHL_31,5": ("Groß", "Paket 31,5 kg"),
        "Hermes_L": ("Groß", "L-Paket"),
    }
    try:
        mapped_shipping_options = [shipping_options_mapping[option] for option in set(ad_cfg.shipping_options)]
    except KeyError as ex:
        raise KeyError(f"Unknown shipping option(s), please refer to the documentation/README: {ad_cfg.shipping_options}") from ex

    shipping_sizes, shipping_packages = zip(*mapped_shipping_options, strict = False)

    try:
        shipping_size, = set(shipping_sizes)
    except ValueError as ex:
        raise ValueError("You can only specify shipping options for one package size!") from ex

    try:
        shipping_size_radio = await scraper.web_find(By.CSS_SELECTOR, f'.SingleSelectionItem--Main input[type=radio][data-testid="{shipping_size}"]')
        shipping_size_radio_is_checked = hasattr(shipping_size_radio.attrs, "checked")

        if shipping_size_radio_is_checked:
            unwanted_shipping_packages = [
                package for size, package in shipping_options_mapping.values()
                if size == shipping_size and package not in shipping_packages
            ]
            to_be_clicked_shipping_packages = unwanted_shipping_packages
        else:
            await scraper.web_click(By.CSS_SELECTOR, f'.SingleSelectionItem--Main input[type=radio][data-testid="{shipping_size}"]')
            to_be_clicked_shipping_packages = list(shipping_packages)

        await scraper.web_click(By.XPATH, '//dialog//button[contains(., "Weiter")]')

        for shipping_package in to_be_clicked_shipping_packages:
            try:
                await scraper.web_click(
                    By.XPATH,
                    f'//dialog//input[contains(@data-testid, "{shipping_package}")]')
            except TimeoutError as ex:
                print(ex)
                # LOG.debug(ex, exc_info = True)

    except TimeoutError as ex:
        print(ex)
        # LOG.debug(ex, exc_info = True)
    try:
        # Click apply button
        await scraper.web_click(By.XPATH, '//dialog//button[contains(., "Fertig")]')
    except TimeoutError as ex:
        raise TimeoutError("Unable to close shipping dialog!") from ex

async def __upload_images(scraper: Scraper, ad_cfg:Ad) -> None:
    if not ad_cfg.images:
        return

    image_upload: Element = await scraper.web_find(By.CSS_SELECTOR, "input[type=file]")
    await image_upload.send_file(*ad_cfg.images)
