#!/usr/bin/env python

from distutils.core import setup

setup(
    name="estool",
    version="1.0",
    description="Implementation of various Evolution Strategies",
    author="David Ha",
    author_email="hardmaru@gmail.com",
    url="https://github.com/hardmaru/estool",
    py_modules=["config", "es", "env", "model", "train"],
    install_requires=[
        "certifi==2020.4.5.2",
        "chardet==3.0.4",
        "cma==2.2.0",
        "gym==0.9.4",
        "idna==2.9",
        "mpi4py==3.0.3",
        "numpy==1.18.5",
        "opencv-python==4.2.0.34",
        "pybullet==2.0.0",
        "pyglet==1.5.5",
        "requests==2.23.0",
        "six==1.15.0",
        "urllib3==1.25.9",
    ],
)
