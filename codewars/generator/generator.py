import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import count
from pathlib import Path
from string import punctuation
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    NamedTuple,
)
from urllib.parse import quote

import click
from bs4 import (
    BeautifulSoup,
    Tag,
)
from requests import (
    codes,
    Response,
    Session,
)

BASE_URL = 'https://www.codewars.com'

BASE_HEADERS = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
                  '(KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36',
}

LANGUAGE_FILE_EXTENSION = {
    'python': 'py',
    'kotlin': 'kt',
    'c': 'c',
    'c++': 'cpp',
    'javascript': 'js',
    'java': 'java',
    'haskell': 'hs',
    'coffeescript': 'coffee',
}
LONGEST_LANGUAGE = max(map(len, LANGUAGE_FILE_EXTENSION)) + 1
NUMBERS = count(1)


class Kata(NamedTuple):
    name: str
    link: str
    kuy: str
    solutions: Dict[str, List[str]]


def create_link(name: str, url: str, wrap: bool = True) -> str:
    """
    Create link in markdown format
    """
    return f'[{name}]({quote(url) if wrap else url})'


def create_readme(base_dir: Path, content: str) -> None:
    """
    Create README.md file in provided directory
    """
    readme = base_dir / 'README.md'
    readme.write_text(content, encoding='utf-8')


def create_path(path: Path) -> Path:
    """
    Create all parents directories for provided path
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def valid_dir_name(name: str):
    """
    Create valid directory name by skipping punctuation characters
    """
    return ''.join(c for c in name if c not in punctuation).strip()


def write_kata(language: str, kata: Kata, kuy_dir: Path) -> None:
    """
    Create directory for kata solution and file with latest kata solution
    """
    kata_dir = create_path(kuy_dir / valid_dir_name(kata.name))

    description = f'# [{kata.name}]({kata.link})'
    print(f'{next(NUMBERS):<5} {language:<{LONGEST_LANGUAGE}} # {kata.name}')
    create_readme(kata_dir, description)

    solution = kata_dir / f'solution.{LANGUAGE_FILE_EXTENSION[language]}'
    solution.write_text(kata.solutions[language][0])


def write_kuy(language: str, kuy: str, katas: List[Kata], language_dir: Path) -> None:
    """
    Create directory for kuy katas and README.md
    """
    kuy_dir = create_path(language_dir / kuy)

    links = (
        (
            create_link(kata.name, f"/codewars/solutions/{language}/{kuy}/{valid_dir_name(kata.name)}"),
            create_link("CodeWard", kata.link, wrap=False),
        )
        for kata in sorted(katas, key=lambda kata: kata.name)
    )

    description = f'# {kuy.title()}\n' + '\n'.join(
        f'* {link} - {codewars_link}' for link, codewars_link in links
    )
    create_readme(kuy_dir, description)

    for kata in katas:
        write_kata(language, kata, kuy_dir)


def write_katas_by_language(language: str, katas: Dict[str, List[Kata]]) -> None:
    """
    Create directory for language katas and README.md
    """
    language_dir = create_path(Path.cwd() / 'solutions' / language)

    data = (
        (
            create_link(kuy, f"/codewars/solutions/{language}/{kuy}"),
            len(katas[kuy]),
        )
        for kuy in sorted(katas)
    )

    description = f'# {language.title()}\n' + '\n'.join(
        f'* :white_check_mark: {link} - {katas_count}' for link, katas_count in data
    )
    create_readme(language_dir, description)

    for kuy, kuy_katas in katas.items():
        write_kuy(language, kuy, kuy_katas, language_dir)


def write_global_readme(information: Dict[str, Any]) -> None:
    """
    Create global README.md with statistic about katas
    """
    readme_template = Path.cwd() / 'README_template.md'

    with readme_template.open(encoding="utf-8") as f:
        template = f.read()

    readme = Path.cwd() / 'README.md'
    readme.write_text(template.format(**information), encoding="utf-8")


def kata_pages(s: Session, auth_token: str, username: str, chunks: int = 10) -> Iterable[Tag]:
    """
    Create generator that concurrently yield all kata solutions for user
    """
    pages = count()
    pool = ThreadPoolExecutor(chunks)

    def fetch(page_number: int) -> Response:
        r = s.get(
            f'{BASE_URL}/users/{username}/completed_solutions',
            headers={
                **BASE_HEADERS,
                'X-Requested-With': 'XMLHttpRequest',
                'Authorization': auth_token,
            },
            params={
                'page': page_number,
            }
        )
        assert r.status_code == codes.ok
        return r

    while True:
        for response in pool.map(fetch, (next(pages) for _ in range(chunks))):
            items = from_response(response).select('.list-item')

            if not items:
                return

            yield from items


def kata_generator(s: Session, auth_token: str, username: str) -> Iterable[Kata]:
    """
    Create generator that yield all kata solutions for user
    """
    for item in kata_pages(s, auth_token, username):
        kuy = item.select_one('.is-extra-wide span,.tag span').text
        kata_ref = item.select_one('div + a[href]')

        name = kata_ref.text
        base_href = kata_ref.attrs['href']

        href = f'{BASE_URL}{base_href}'

        solutions = defaultdict(list)
        language = None

        for part in item.select('.item-title ~ .markdown, .item-title ~ h6'):
            if part.name == 'h6':
                language, *_ = part.text.split(':')
                language = language.strip().lower()
            else:
                assert language is not None, "Language must be set"
                code = part.select_one('code').text

                solutions[language].append(code)

        yield Kata(
            name=name,
            link=href,
            kuy=kuy,
            solutions={**solutions},
        )


def from_response(r: Response) -> BeautifulSoup:
    """
    Convert Response text to BeautifulSoup instance using html.parser feature
    """
    return BeautifulSoup(r.text, features="html.parser")


@click.command()
@click.option(
    '-u',
    '--username',
    type=str,
)
@click.option(
    '-p',
    '--password',
    type=str,
)
@click.option(
    '-e', '--email',
    type=str,
)
def main(username: str, password: str, email: str) -> None:
    with Session() as s:
        r = s.get(f'{BASE_URL}/users/sign_in')
        assert r.status_code == codes.ok

        root = from_response(r)
        auth_token = root.select_one('input[name="authenticity_token"]').attrs['value']

        # Login to codewars using email and password provided from cli
        r = s.post(
            f'{BASE_URL}/users/sign_in',
            headers=BASE_HEADERS,
            data={
                'utf-8': '',
                'authenticity_token': auth_token,
                'user[email]': email,
                'user[password]': password,
                'user[remember_me]': 'true',
            },
        )
        assert r.status_code == codes.ok

        # Group all katas by language and kuy
        katas: Dict[str, Dict[str, List[Kata]]] = defaultdict(lambda: defaultdict(list))

        for kata in kata_generator(s, auth_token, username):
            for language in kata.solutions:
                katas[language][kata.kuy].append(kata)

        # Dump all katas in format:
        # * Language:
        #       * Kuy 1:
        #           * Kata 1
        #           * Kata 2
        #           * Kata 3
        #
        #       * Kuy 2:
        #           * Kata 1
        #           * Kata 2
        #           * Kata 3
        #
        #       * Kuy 3:
        #           * Kata 1
        #           * Kata 2
        #           * Kata 3
        #
        for language, lang_katas in katas.items():
            write_katas_by_language(language, lang_katas)

        r = s.get(
            f'{BASE_URL}/users/{username}',
            headers=BASE_HEADERS,
        )
        assert r.status_code == codes.ok

        root = from_response(r)
        # Fetch info about every language kuy
        data = {
            honor.contents[0].text.split(':')[0].lower() + '-kuy': honor.contents[-1]
            for honor in root.select('.honor')
        }

        total_katas = re.search(r'(?<=Total Completed Kata:)\d+', root.text).group()
        data['overall-katas'] = total_katas

        # Add information about completed katas
        data.update({
            f'{language}-katas': sum(map(len, all_katas.values()))
            for language, all_katas in katas.items()
        })

        write_global_readme(data)


if __name__ == '__main__':
    main()
