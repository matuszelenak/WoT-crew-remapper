import os
import re
from dataclasses import dataclass, field
from typing import List, Generator, Tuple, Dict, Set

import polib as polib
from flask import Flask, render_template, request, send_file
from whitenoise import WhiteNoise
import zipfile
from io import BytesIO

from lxml import etree
from lxml.etree import Element

BASE_DIR = os.path.dirname(__file__)


class MoFileCache:
    def __init__(self, path):
        self.cache = {}
        for filename in os.listdir(path):
            self.cache[os.path.splitext(filename)[0]] = polib.mofile(os.path.join(path, filename))

    def __getattr__(self, item):
        return self.cache.get(item, polib.MOFile())

    def get_name(self, user_string: str):
        if not user_string:
            return None
        match = re.search("#(?P<filename>[a-zA-Z0-9_-]+):(?P<slug>.+)", user_string)
        if not match:
            return None
        mo_filename = match.groupdict()['filename']
        slug = match.groupdict()['slug']
        entry = getattr(self, mo_filename, None).find(slug)
        if entry:
            return entry.msgstr


def load_xml(path) -> Element:
    with open(path) as f:
        return load_xml_from_str(f.read())


def load_xml_from_str(content) -> Element:
    parser = etree.XMLParser(recover=True)
    return etree.fromstring(content, parser)


def load_special_voice_tags() -> Generator[str, None, None]:
    root = load_xml(os.path.join(BASE_DIR, 'special_voices.xml'))
    for tank_man in root.find('voiceover'):
        yield tank_man.find('tag').text.strip()


@dataclass
class SubstitutionData:
    first_name: str
    last_name: str
    icon: str
    tags: str


@dataclass
class Tankman:
    first_name: str
    last_name: str
    icon: str
    slug: str
    voice_tag: str
    nation_data: Dict[str, SubstitutionData] = field(default_factory=dict)


class TankStylesApp(Flask):
    nation_xmls: Dict[str, str] = {}
    tankmen: Dict[str, Tankman] = {}
    g_mo_cache = MoFileCache(os.path.join(BASE_DIR, 'mo'))

    def __init__(self, *args, **kwargs):
        voice_tags = set(load_special_voice_tags())
        self.load_tankmen(voice_tags)
        super().__init__(*args, **kwargs)

    def load_tankmen(self, voice_tags: Set[str]):
        for filename in os.listdir('tankmen'):
            nation = os.path.splitext(filename)[0]

            with open(os.path.join(BASE_DIR, 'tankmen', filename)) as f:
                content = f.read()
                self.nation_xmls[nation] = content
                root = load_xml_from_str(content)

            for tankman in root.find('premiumGroups'):
                slug = tankman.tag
                tags = set(getattr(tankman.find('tags'), 'text', '').strip().split(' '))
                voice_tag = next(iter(tags & voice_tags), None)
                if not voice_tag:
                    continue

                first_name = next(iter(tankman.find('firstNames'))).text
                try:
                    second_name = next(iter(tankman.find('lastNames'))).text
                except:
                    second_name = None
                icon = next(iter(tankman.find('icons'))).text
                if slug not in self.tankmen:
                    self.tankmen[slug] = Tankman(
                        self.g_mo_cache.get_name(first_name.strip()),
                        self.g_mo_cache.get_name(second_name.strip()),
                        icon.strip(),
                        slug,
                        voice_tag
                    )
                    print(icon)

                self.tankmen[slug].nation_data[nation] = SubstitutionData(
                    first_name,
                    second_name,
                    icon,
                    getattr(tankman.find('tags'), 'text', '')
                )

    def substitute(self, nation, substitutions: Dict[str, str]) -> str:
        xml = load_xml_from_str(self.nation_xmls[nation])
        for tankman in xml.find('premiumGroups'):
            if tankman.tag in substitutions:
                source = self.tankmen[tankman.tag]
                target = self.tankmen[substitutions[tankman.tag]]
                tankman.find('tags').text = target.nation_data[nation].tags.replace(source.voice_tag, target.voice_tag)
                next(iter(tankman.find('firstNames'))).text = target.nation_data[nation].first_name
                next(iter(tankman.find('lastNames'))).text = target.nation_data[nation].last_name
                next(iter(tankman.find('icons'))).text = target.nation_data[nation].icon

        return etree.tostring(xml).decode()


app = TankStylesApp(__name__)
app.wsgi_app = WhiteNoise(
    app.wsgi_app,
    root=os.path.join(os.path.dirname(__file__), "static"),
    max_age=31536000 if not app.config["DEBUG"] else 0
)


@app.route('/', methods=['GET', 'POST'])
def tankmen():
    # if request.method == 'POST':
    #     files = get_styled_files(request.form)
    #     if files:
    #         return create_zip_file(files)
    #
    # sorted_vehicles = sorted(app.vehicles.values(), key=lambda vehicle: (vehicle['nation'], vehicle['name']))
    # by_nation = group_by_attribute(sorted_vehicles, lambda vehicle: vehicle['nation'])
    # in_nation_sorted = {
    #     nation: sorted(vehicles, key=lambda vehicle: (vehicle['class'], -vehicle['tier'], vehicle['name']))
    #     for nation, vehicles in by_nation.items()
    # }
    return render_template('tankmen.html', tankmen=app.tankmen.values())


if __name__ == "__main__":
    app.run(debug=True, threaded=True, host='0.0.0.0', port=8000)
