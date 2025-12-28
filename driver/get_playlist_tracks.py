# get_playlist_tracks.py

from dataclasses import dataclass, field
import time
import json
import re
from bs4 import BeautifulSoup
from core.driver.chrome_chromedriver_test import MyDriver


@dataclass
class GetPlaylistTracksClean:
    id_tg_user: int
    playlist_url: str
    step_size: int = 900
    pause_after_scroll: float = 5.0
    max_no_new: int = 2

    driver = MyDriver().get_driver
    # Имена файлов вычисляем динамически после инициализации
    tracks_file_txt: str = field(init=False)
    tracks_file_json: str = field(init=False)

    def __post_init__(self):
        # Теперь id_tg_user доступен — формируем имена файлов
        self.tracks_file_txt = f"playlist_tracks_{self.id_tg_user}.txt"
        self.tracks_file_json = f"playlist_tracks_{self.id_tg_user}.json"

        self.run()

    def run(self):
        print(f"[User {self.id_tg_user}] Открываю плейлист: {self.playlist_url}")
        self.driver.get(self.playlist_url)
        time.sleep(8)

        print("Удаляю боковую панель и баннер...")
        self._remove_sidebar_and_banner()

        print("Собираем уже видимые треки (первые, загруженные сразу)...")
        all_tracks = set(self._parse_tracks_raw())
        print(f"Найдено изначально: {len(all_tracks)} треков")

        print(f"Запускаю цикл скролл → пауза → парсинг (шаг {self.step_size}px, пауза {self.pause_after_scroll}s)...")
        tracks = self._scroll_and_parse_progressive(all_tracks)

        if tracks:
            print(f"\nУспешно собрано {len(tracks)} уникальных треков!")
            self._save_tracks(tracks)
            print(f"Сохранено в {self.tracks_file_txt} и {self.tracks_file_json}")
        else:
            print("Треки не были собраны.")

        # НЕ закрываем браузер автоматически — пусть пользователь закроет вручную или добавим таймаут
        print("Парсинг завершён. Браузер можно закрыть вручную.")

    def _remove_sidebar_and_banner(self):
        js_remove = """
        let sidebar = document.querySelector('aside[class*="Navbar_root"]');
        if (sidebar) sidebar.remove();

        let banner = document.querySelector('section[class*="SideAdvertBanner_root"]');
        if (banner) banner.remove();
        """
        self.driver.execute_script(js_remove)
        time.sleep(1)

    def _scroll_and_parse_progressive(self, initial_tracks_set):
        all_tracks = initial_tracks_set
        no_new_tracks_count = 0
        step_count = 0

        while no_new_tracks_count < self.max_no_new:
            step_count += 1
            print(f"Шаг {step_count}: скроллим на {self.step_size}px...")

            js_scroll_step = f"""
            let container = document.querySelector('[data-virtuoso-scroller="true"]');
            if (!container) return null;

            container.scrollTop += {self.step_size};

            if (container.scrollTop + container.clientHeight + 500 >= container.scrollHeight) {{
                container.scrollTop = container.scrollHeight;
            }}

            return container.scrollHeight;
            """
            result = self.driver.execute_script(js_scroll_step)
            if result is None:
                print("Ошибка: Virtuoso scroller не найден.")
                break

            print(f"  Пауза {self.pause_after_scroll} сек на подгрузку...")
            time.sleep(self.pause_after_scroll)

            current_tracks = self._parse_tracks_raw()

            before = len(all_tracks)
            for track in current_tracks:
                all_tracks.add(track)
            after = len(all_tracks)
            new_added = after - before

            if new_added == 0:
                no_new_tracks_count += 1
                print(f"  → Нет новых треков ({no_new_tracks_count}/{self.max_no_new})")
            else:
                no_new_tracks_count = 0
                print(f"  → Добавлено {new_added} новых треков (всего: {after})")

        print(f"\nСбор завершён! Всего уникальных треков: {len(all_tracks)}")
        return sorted(list(all_tracks))

    def _parse_tracks_raw(self):
        """ Парсит текущие видимые треки из HTML, убирает '-' для безопасности """
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')

        current = []
        track_links = soup.find_all('a', class_=re.compile(r'Meta_albumLink__', re.I))

        for link in track_links:
            title_span = link.find('span', class_=re.compile(r'Meta_title__', re.I))
            if not title_span:
                continue
            title = title_span.get_text(strip=True)

            artist_span = link.find_next('span', class_=re.compile(r'Meta_subtitle__|artist', re.I))
            artists = artist_span.get_text(strip=True, separator=', ') if artist_span else "Unknown Artist"

            # УБИРАЕМ ВСЕ ДЕФИСЫ из названия и артистов
            clean_title = title.replace('-', '').strip()
            clean_artists = artists.replace('-', '').strip()

            # Формируем строку без дефиса
            clean_track = f"{clean_title} {clean_artists}".strip()

            current.append(clean_track)

        return current

    def _save_tracks(self, tracks):
        with open(self.tracks_file_txt, 'w', encoding='utf-8') as f:
            for i, track in enumerate(tracks, 1):
                f.write(f"{i}. {track}\n")

        json_data = {
            "playlist_url": self.playlist_url,
            "total_tracks": len(tracks),
            "complite_download": 0,  # Здесь можно обновлять при отправке треков
            "tracks": tracks
        }
        with open(self.tracks_file_json, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)


def Startparser(playlist_url: str, id_tg_user: int):
    """
    Запуск парсера для конкретного пользователя
    """
    GetPlaylistTracksClean(
        id_tg_user=id_tg_user,
        playlist_url=playlist_url,
        pause_after_scroll=5.0,
        step_size=900
    )


# ----------------- ТЕСТОВЫЙ ЗАПУСК -----------------
if __name__ == "__main__":
    test_url = "https://music.yandex.ru/playlists/05a74673-8b71-4f78-99ec-ee2640e26886"
    test_user_id = 123456789
    Startparser(test_url, test_user_id)