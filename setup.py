from setuptools import setup

import versioneer

setup(
    name="anaconda-anon-usage",
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    description="basic anonymous telemetry for conda",
    license="BSD",
    author="Michael C. Grant",
    author_email="mgrant@anaconda.com",
    url="https://github.com/Anaconda-Platform/anaconda-ident",
    packages=["anaconda_anon_usage"],
    install_requires=["conda"],
    keywords=["anaconda-anon-usage"],
    entry_points={
        "conda": [
            "anaconda-anon-usage-plugin = anaconda_anon_usage.plugin",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)
