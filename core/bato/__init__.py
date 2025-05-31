from plugins.base import MangaPluginBase, Formats, AgeRating, Status, NO_THUMBNAIL_URL, DATETIME_FORMAT
import requests
from bs4 import BeautifulSoup
from lxml import etree
from datetime import datetime, timezone
import re

import logging
logger = logging.getLogger(__name__)

class BatoPlugin(MangaPluginBase):
    languages = ["en"]
    base_url = "https://bato.to"

    def search_manga(self, query:str, language:str=None) -> list[dict]:
        logger.debug(f'Searching for "{query}"')
        try:
            response = requests.get(f'{self.base_url}/v3x-search',
                                        params={
                                            "word": query.lower(),
                                            "lang": "en",
                                        },
                                        timeout=10
                                        )
            
            response.raise_for_status()

            return self.get_manga_list_from_html(response.text)

        except Exception as e:
            logger.error(f'Error while searching manga - {e}')
        return []
    
    def get_manga_list_from_html(self, document) -> list[dict]:
        soup = BeautifulSoup(document, 'lxml')
        dom = etree.HTML(str(soup))
        mangaList = dom.xpath("//div[@data-hk='0-0-2']")

        if not mangaList:
            return []
        
        manga_node = mangaList[0]

        div_children = manga_node.xpath("./div")
        if not div_children:
            return []
        
        found_mangas = []
        for id, child in enumerate(manga_node):
            if not isinstance(child.tag, str):
                continue

            first_desc_divs = child.xpath(".//div")
            if not first_desc_divs:
                continue

            first_div = first_desc_divs[0]
            if len(first_div) == 0:
                continue

            last_div = first_desc_divs[-1]
            if len(last_div) == 0:
                continue

            first_child = first_div[0]
            href = first_child.get("href", "")
            img = first_child.find("img") if hasattr(first_child, 'find') else None
            img_src = img.get("src", "") if img is not None else NO_THUMBNAIL_URL
            if href:
                found_mangas.append((f"{self.base_url}{href}", img_src))

        mangaData = []

        for url, cover in found_mangas:
            manga_dict = self.search_manga_dict()
            manga_dict["url"] = url
            manga_dict["cover"] = cover

            name = self.get_manga(manga_dict).get("name")
            if name is None or len(name) == 0:
                continue
            manga_dict["name"] = name
            mangaData.append(manga_dict)


        return mangaData

    def get_manga(self, arguments:dict) -> dict:
        try:
            url = arguments.get("url")
            if url is None:
                raise Exception("There is no URL in arguments")
            response = requests.get(url,
                                    timeout=10
                                    )
            response.raise_for_status()

            return self.get_manga_from_html(response.text, url)

        except Exception as e:
            logger.error(f'Error while getting manga - {e}')

        return {}
    
    def get_manga_from_html(self, document, url) -> dict:
        soup = BeautifulSoup(document, 'lxml')
        dom = etree.HTML(str(soup))
        info_nodes = dom.xpath("/html/body/div/main/div[1]/div[2]")
        manga = self.get_manga_dict()
        if not info_nodes:
            return manga
        info_node = info_nodes[0]


        sort_name_nodes = info_node.xpath(".//h3/a")
        manga["name"] = sort_name_nodes[0].text.strip() if sort_name_nodes else ""

        desc_node = dom.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' prose ')]/div")
        manga["description"] = desc_node[0].text.strip() if desc_node else ""


        img_nodes = dom.xpath("//img[@data-hk='0-1-0']")
        manga["poster_url"] = img_nodes[0].get("src", "").replace("&amp;", "&") if img_nodes else ""


        genre_span_nodes = dom.xpath("//b[text()='Genres:']/..//span")
        manga["genres"] = [node[0].text.strip() for node in genre_span_nodes if len(node) > 0]

        author_a_nodes = info_node[1][3].xpath(".//a") if len(info_node) > 1 and len(info_node[1]) > 3 else []
        manga["authors"] = [node.text.strip().replace("amp;", "") for node in author_a_nodes]


        lang_node = dom.xpath("//span[text()='Tr From']/..")
        manga["original_language"] = lang_node[0][-1].text.strip() if lang_node and len(lang_node[0]) > 0 else ""


        year_node = dom.xpath("//span[text()='Original Publication:']/..")
        if year_node and len(year_node[0]) > 0:
            try:
                year_text = year_node[0][-1].text.strip().split("-")[0]
                year = int(year_text)
            except (ValueError, IndexError):
                year = datetime.now().year
        else:
            year = datetime.now().year
        manga["year"] = year


        status_node = year_node[0] if year_node else None
        status_text = status_node[2].text.strip().lower() if status_node is not None and len(status_node) > 2 else ""

        release_status_map = {
            "ongoing": Status.ONGOING,
            "completed": Status.COMPLETED,
            "hiatus": Status.HIATUS,
            "cancelled": Status.CANCELLED,
            "pending": Status.UNKNOWN
        }

        manga["complete"] = release_status_map.get(status_text, Status.UNKNOWN) == Status.COMPLETED
        manga["url"] = url

        return manga
    
    def get_chapters(self, arguments:dict) -> list[dict]:
        try:
            url = arguments.get("url")
            if url is None:
                raise Exception("There is no URL in arguments")
            response = requests.get(url,
                                    timeout=10
                                    )
            response.raise_for_status()

            return self.get_chapters_list_from_html(response.text, arguments)

        except Exception as e:
            logger.error(f'Error while getting manga - {e}')

        return []
    
    def get_chapters_list_from_html(self, document, arguments) -> list[dict]:
        soup = BeautifulSoup(document, 'lxml')
        dom = etree.HTML(str(soup))
        chapterList = dom.xpath("/html/body/div/main/div[3]/astro-island/div/div[2]/div/div/astro-slot")[0]

        number_rex = re.compile(r"/title/.+/([0-9]+)(?:-vol_([0-9]+))?-ch_([0-9.]+)")

        chapters = []
        for chapterInfo in chapterList.xpath("./div"):
            infoNode = chapterInfo[0][0]
            chapterUrl = infoNode.get("href", "")
            releaseNode = chapterInfo.xpath(f".//time")
            releaseDate = releaseNode[0].get("time")

            match = number_rex.match(chapterUrl)
            chapter = self.get_chapter_dict()
            chapter["isbn"] = match.group(1)
            chapter["volume_number"] = match.group(2) if match.group(2) else 1.0
            chapter["chapter_number"] = match.group(3)
            chapter["name"] = chapter["chapter_number"]
            chapter["url"] = f'{self.base_url}{chapterUrl}?load=2'
            chapter["source_url"] = chapter["url"]
            chapter["localization"] = "en"
            chapter["release_date"] = datetime.strptime(releaseDate, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)

            if arguments.get("description"):
                chapter["description"] = arguments["description"]

            chapter["arguments"] = arguments
            chapters.append(chapter)

        return chapters
    
    def get_pages(self, arguments:dict) -> list[dict]:
        try:
            url = arguments.get("url")
            if url is None:
                raise Exception("There is no URL in arguments")
            response = requests.get(url,
                                    timeout=10
                                    )
            response.raise_for_status()

            return self.get_pages_list_from_html(response.text, arguments)

        except Exception as e:
            logger.error(f'Error while getting manga - {e}')

        return []
    
    def get_pages_list_from_html(self, document, arguments) -> list[dict]:
        soup = BeautifulSoup(document, 'lxml')
        dom = etree.HTML(str(soup))

        astro_islands = dom.xpath("//astro-island[contains(@component-url, '/_astro/ImageList.')]")
        if not astro_islands:
            raise ValueError("No matching astro-island found")

        images = astro_islands[0]

        weird_string = etree.tostring(images, encoding="unicode")

        match = re.search(r'props="(.*?})"', weird_string)
        if not match:
            raise ValueError("No props found")
        weird_string2 = match.group(1)

        urls = re.findall(r'(https:\/\/[A-z\-0-9\.\?\&\;\=\/]+)\\', weird_string2)
        urls = [{"url": url.replace("&amp;", "&"), "arguments": arguments} for url in urls]
        return urls