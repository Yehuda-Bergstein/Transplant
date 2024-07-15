from enum import Enum
import requests


def ra_rehost(img_link, key):
    url = "https://thesungod.xyz/api/image/rehost_new"
    data = {'api_key': key,
            'link': img_link}
    r = requests.post(url, data=data)
    return r.json()['link']


def ptpimg_rehost(img_link, key):
    url = "https://ptpimg.me/"
    data = {'api_key': key,
            'link-upload': img_link}
    r = requests.post(url + 'upload.php', data=data)
    rj = r.json()[0]
    return f"{url}{rj['code']}.{rj['ext']}"


def imgbb_rehost(img_link, key):
    url = 'https://api.imgbb.com/1/upload'
    data = {'key': key,
            'image': img_link}
    r = requests.post(url, data=data)
    return r.json()['data']['url']


class IH(Enum):
    Ra = 0
    PTPimg = 1
    ImgBB = 2

    def __init__(self, value):
        self.key = ''
        self.enabled = False
        self.prio = value
        self.func = globals()[f'{self.name.lower()}_rehost']

    @property
    def key(self):
        return self._key

    @key.setter
    def key(self, key: str):
        self._key = key.strip()

    def extra_attrs(self):
        return self.enabled, self.key, self.prio

    def set_extras(self, enabled, key, prio):
        self.enabled = enabled
        self.key = key
        self.prio = prio

    @classmethod
    def set_attrs(cls, attr_dict: dict):
        for name, attrs in attr_dict.items():
            mem = cls[name]
            if mem:
                mem.set_extras(*attrs)

    @classmethod
    def get_attrs(cls) -> dict:
        attr_dict = {}
        for mem in cls:
            attr_dict[mem.name] = mem.extra_attrs()
        return attr_dict

    @classmethod
    def prioritised(cls) -> list:
        return sorted(cls, key=lambda m: m.prio)

    @classmethod
    def rehost(cls, img_link: str) -> str:
        for host in cls.prioritised():
            if not host.enabled:
                continue
            args = [img_link]
            if host.key:
                args.append(host.key)
            try:
                return host.func(*args)
            except Exception:
                continue
