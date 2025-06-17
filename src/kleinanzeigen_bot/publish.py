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
    ad_files = [file for match in config.ad_files for file in glob.glob(match)]
    if len(ad_files) == 0:
        print("no ad files found")
        return

    browser = await create_browser_session(config.browser_socket)
    tab = await browser.get(URL)
    scraper = Scraper(tab)
    await scraper.ensure_logged_in(config.username)

    published_ads = await get_all_published_ads(scraper)
    published_ids = list(map(lambda ad: int(ad['id']), published_ads))

    working_tab = await browser.get(f"{URL}/p-anzeige-aufgeben-schritt2.html", new_tab=True)
    scraper = Scraper(working_tab)

    for (i, file) in enumerate(ad_files):
        print(f"processing {i+1}/{len(ad_files)} ad")
        ad = load_ad(file)
        if ad.id is not None and ad.id in published_ids:
            print(f"skipping ad {ad.id} - already processed")
            continue

        await scraper.goto(f"{URL}/p-anzeige-aufgeben-schritt2.html")

        try:
            id = await publish_ad(scraper, ad.to_ad(config.ad_defaults), file)
            with open(file, 'w') as f:
                ad.id = id
                f.write(ad.model_dump_json())

            print("ad published with id:", id)
        except Exception as e:
            print(e)

        
   

async def publish_ad(scraper: Scraper, ad: Ad, file_path: str):
    await scraper.input(By.CSS_SELECTOR, "#postad-title", ad.title)
    
    await scraper.input(By.CSS_SELECTOR, "input#post-ad-frontend-price, input#micro-frontend-price, input#pstad-price", str(ad.price))
    await scraper.web_select(By.CSS_SELECTOR, "#micro-frontend-price-type", "NEGOTIABLE")

    await __set_category(scraper, "210/223/ersatz_reparaturteile")
    await __set_shipping(scraper, ad)

    await scraper.script("document.querySelector('#pstad-descrptn').value = `" + ad.description.replace("`", "'") + "`")
    
    await __upload_images(scraper, ad, file_path)

    await scraper.detect_captcha()

    try:
        submit_button = await scraper.query(By.CSS_SELECTOR, "#pstad-submit")
        await submit_button.scroll_into_view()
        await scraper.sleep(500, 1000)
        await submit_button.click()
    except TimeoutError:
        # https://github.com/Second-Hand-Friends/kleinanzeigen-bot/issues/40
        await scraper.click(By.XPATH, "//fieldset[@id='postad-publish']//*[contains(., 'Anzeige aufgeben')]")
        await scraper.click(By.CSS_SELECTOR, "#imprint-guidance-submit")

    # no image question
    try:
        image_hint_xpath = '//*[contains(@class, "ModalDialog--Actions")]//button[contains(., "Ohne Bild veröffentlichen")]'
        if not ad.images and await scraper.web_check(By.XPATH, image_hint_xpath, Is.DISPLAYED):
            await scraper.click(By.XPATH, image_hint_xpath)
    except TimeoutError:
        pass

    await scraper.wait_for(lambda: "p-anzeige-aufgeben-bestaetigung.html?adId=" in scraper.page.url, timeout = 20)

    # extract the ad id from the URL's query parameter
    current_url_query_params = urllib.parse.parse_qs(urllib.parse.urlparse(scraper.page.url).query)
    ad_id = int(current_url_query_params.get("adId", [])[0])

    # check for approval message
    try:
        approval_link_xpath = '//*[contains(@id, "not-completed")]//a[contains(@class, "to-my-ads-link")]'
        if await scraper.web_check(By.XPATH, approval_link_xpath, Is.DISPLAYED):
            await scraper.click(By.XPATH, approval_link_xpath)
    except TimeoutError:
        pass 

    return ad_id

async def __set_category(scraper: Scraper, category: str) -> None:
    await scraper.click(By.CSS_SELECTOR, "#pstad-descrptn")

    try:
        if await scraper.get_inner_text(By.CSS_SELECTOR, "#postad-category-path"):
            return
    except TimeoutError:
        pass

    if not category:
        raise Exception("no category was supplied and category auto-detection failed")
    
    await scraper.sleep()  # workaround for https://github.com/Second-Hand-Friends/kleinanzeigen-bot/issues/39
    await scraper.click(By.CSS_SELECTOR, "#pstad-lnk-chngeCtgry")
    await scraper.query(By.CSS_SELECTOR, "#postad-step1-sbmt")

    category_url = f"{URL}/p-kategorie-aendern.html#?path={category}"
    await scraper.goto(category_url)
    await scraper.click(By.XPATH, "//*[@id='postad-step1-sbmt']/button")



async def __set_shipping(scraper: Scraper, ad_cfg:Ad) -> None:
    if ad_cfg.shipping_type == "PICKUP":
        try:
            await scraper.click(By.XPATH, '//*[contains(@class, "ShippingPickupSelector")]//label[contains(., "Nur Abholung")]/../input[@type="radio"]')
        except TimeoutError as ex:
            print(ex)
            # LOG.debug(ex, exc_info = True)
    elif ad_cfg.shipping_options:
        await scraper.click(By.XPATH, '//*[contains(@class, "SubSection")]//button[contains(@class, "SelectionButton")]')
        await scraper.click(By.XPATH, '//*[contains(@class, "CarrierSelectionModal")]//button[contains(., "Andere Versandmethoden")]')
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
                    await scraper.click(By.XPATH, '//*[contains(@class, "SubSection")]//button[contains(@class, "SelectionButton")]')
                    await scraper.click(By.XPATH, '//*[contains(@class, "CarrierSelectionModal")]//button[contains(., "Andere Versandmethoden")]')
                    await scraper.click(By.XPATH, '//*[contains(@id, "INDIVIDUAL") and contains(@data-testid, "Individueller Versand")]')
                    await scraper.input(By.CSS_SELECTOR, '.IndividualShippingInput input[type="text"]', str.replace(str(ad_cfg.shipping_costs), ".", ","))
                    await scraper.click(By.XPATH, '//dialog//button[contains(., "Fertig")]')
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
        shipping_size_radio = await scraper.query(By.CSS_SELECTOR, f'.SingleSelectionItem--Main input[type=radio][data-testid="{shipping_size}"]')
        shipping_size_radio_is_checked = hasattr(shipping_size_radio.attrs, "checked")

        if shipping_size_radio_is_checked:
            unwanted_shipping_packages = [
                package for size, package in shipping_options_mapping.values()
                if size == shipping_size and package not in shipping_packages
            ]
            to_be_clicked_shipping_packages = unwanted_shipping_packages
        else:
            await scraper.click(By.CSS_SELECTOR, f'.SingleSelectionItem--Main input[type=radio][data-testid="{shipping_size}"]')
            to_be_clicked_shipping_packages = list(shipping_packages)

        await scraper.click(By.XPATH, '//dialog//button[contains(., "Weiter")]')

        for shipping_package in to_be_clicked_shipping_packages:
            try:
                await scraper.click(
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
        await scraper.click(By.XPATH, '//dialog//button[contains(., "Fertig")]')
    except TimeoutError as ex:
        raise TimeoutError("Unable to close shipping dialog!") from ex


def resolve_relative_path(base_file_path: str, relative_path: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(base_file_path))
    return os.path.abspath(os.path.join(base_dir, relative_path))

async def __upload_images(scraper: Scraper, ad_cfg: Ad, file_path: str) -> None:
    if not ad_cfg.images:
        return

    image_upload: Element = await scraper.query(By.CSS_SELECTOR, "input[type=file]")
    await image_upload.send_file(*map(lambda image: resolve_relative_path(file_path, image), ad_cfg.images))
    await scraper.sleep()
