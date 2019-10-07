#!/usr/bin/env python3

from setuptools import setup
from pathlib import Path

readme = Path("README.md").read_text()


setup(
    name="wifireconnect",
    packages=["wifireconnect"],
    entry_points={
        "console_scripts": [
            "wifireconnect = wifireconnect.__main__:main"
        ]
    },
    version="0.1.1",
    license="GPL3",
    description="Python3 module to test and ensure connectivity "
    "on a network which have stability problems on"
    " traffic routing (link layer).",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="Carlos A. Planchón",
    author_email="bubbledoloresuruguay2@gmail.com",
    url="https://github.com/carlosplanchon/wifireconnect",
    download_url="https://github.com/carlosplanchon/"
        "wifireconnect/archive/v0.1.1.tar.gz",
    keywords=["wifi", "connectivity", "networking"],
    install_requires=[
        "pingparsing"
    ],
    classifiers=[
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3.7",
    ],
)
