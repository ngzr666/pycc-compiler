from setuptools import setup, find_packages
import shutil
import sys

TERMUX_PATH = "/data/data/com.termux/files/usr/bin/termux-change-repo"

def check_termux():
    path = shutil.which('termux-change-repo')
    if path != TERMUX_PATH:
        print("Only Termux")
        sys.exit(1)

check_termux()

VERSION = "1.5.2"
DESCRIPTION = "Compile python to ELF (Only Termux)"

setup(
    name="pycc-compiler",
    version=VERSION,
    description=DESCRIPTION,
    long_description=DESCRIPTION,
    packages=find_packages(),
    py_modules=["pycc"],
    install_requires=["cython>=3.0.0"],
    entry_points={"console_scripts": ["pycc=pycc:main"]},
    python_requires=">=3.8",
)
