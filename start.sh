#!/usr/bin/env bash
# install pip dependencies
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt

# make sure static dir exists
mkdir -p static

# start uvicorn
uvicorn api:app --host 0.0.0.0 --port 3000
