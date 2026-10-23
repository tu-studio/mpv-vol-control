from os import makedirs
import socket
import json

import time
from pathlib import Path

import subprocess

from imgui_bundle import imgui, hello_imgui


socket_path = "/tmp/mpvsocket"
state_path = Path.home() / Path(".local/state/mpv_vol_ctrl/")
state_file = "state.txt"

vol_prefix = "VOL="


def read_state():
    global volume
    try:
        with open(state_path / state_file) as f:
            for line in f:
                if line.startswith(vol_prefix):

                    volume = int(line.strip("\n").removeprefix(vol_prefix))
    except Exception as e:
        print(f"reading state failed: {e}")
        print("using default volume 50")
        volume = 50


def save_state():
    state_path.mkdir(parents=True, exist_ok=True)

    print("saving")
    makedirs(state_path, exist_ok=True)
    with open(state_path / state_file, mode="w") as f:
        f.write(f"{vol_prefix}{volume}\n")


# Create a Unix domain socket connection
def connect():
    global client, is_connected
    is_connected = False
    while is_connected == False:
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(socket_path)
            client.settimeout(0.5)
            is_connected = True
        except Exception as e:
            print(f"failed to connect to ipc socket, reason: {e}. retrying...")
            time.sleep(3)
    set_volume(volume)


class NoResponseException(Exception):
    pass


def parse_responses(response: str):
    responses = response.split("\n")
    for res in responses:
        if res == "":
            continue
        try:
            r = json.loads(res)

        except json.JSONDecodeError as e:
            print()
            continue
        if "event" in r:
            print(f"got event {r["event"]}")
            continue

        if "data" in r:
            return r["data"]
        if r["error"] != "success":
            raise Exception(r["error"])
        if r["error"] == "success":
            return None
    raise NoResponseException()


def send_message(payload: dict):
    message = json.dumps(payload) + "\n"
    # Send the command to mpv

    while True:
        try:
            client.sendall(message.encode("utf-8"))

            # Read the response from the server
            response = client.recv(1024).decode()

            break
        except Exception:
            connect()
    try:
        return parse_responses(response)
    except NoResponseException:
        try:
            response = client.recv(1024).decode()
            return parse_responses(response)
        except TimeoutError:
            return None
        except Exception:
            connect()
    return None


def set_volume(volume: int):
    payload = {"command": ["set_property", "volume", volume]}
    send_message(payload)


def set_mute(muted: bool):
    payload = {"command": ["set_property", "mute", muted]}
    send_message(payload)


def get_volume():
    payload = {"command": ["get_property", "volume"]}
    volume = None
    while volume is None:
        volume = send_message(payload)
    return volume


def get_mute():
    payload = {"command": ["get_property", "mute"]}
    mute = None
    while mute is None:
        mute = send_message(payload)
    return mute


def set_pause(pause_state: bool):
    payload = {"command": ["set_property", "pause", pause_state]}
    send_message(payload)


volume = 0
muted = False
next_update = 0
next_save = 0
update_timeout = 0.5
state_save_timeout = 1


def gui():
    global volume, next_update, next_save, muted
    if not is_connected:
        imgui.text("not connected")
    window_size = imgui.get_window_size()
    slider_width = window_size.x / 3
    slider_height = window_size.y * 0.75

    imgui.spacing()

    imgui.push_font(None, 30.0)
    imgui.set_cursor_pos_x((window_size.x - imgui.calc_text_size("Volume").x) / 2)
    imgui.text("Volume")
    imgui.set_cursor_pos_x(window_size.x / 3)

    vol_changed, new_vol = imgui.v_slider_int(
        "##", (slider_width, slider_height), volume, 0, 130
    )
    imgui.dummy((0, 30))
    imgui.set_cursor_pos_x(window_size.x / 3)

    imgui.push_id("mute_button")
    button_pressed = imgui.button("muted" if muted else "not muted", (slider_width, 60))
    imgui.pop_id()

    imgui.pop_font()

    if vol_changed and new_vol != volume:
        set_volume(new_vol)
        volume = new_vol
    if button_pressed:
        muted = not muted
        set_mute(muted)

    if not vol_changed or button_pressed and next_update < time.time():
        volume = int(get_volume())
        muted = bool(get_mute())
        next_update = time.time() + update_timeout

    if not vol_changed and next_save < time.time():
        save_state()
        next_save = time.time() + state_save_timeout


def is_display_connected():
    p = subprocess.run(
        "xrandr --current", stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
    )
    return p.returncode == 0 and "*" in p.stdout.decode()


def main():
    read_state()
    connect()
    # Prepare the payload with a trailing newline
    global muted
    muted = bool(get_mute())
    while True:
        if is_display_connected():
            hello_imgui.run(gui, window_title="volume control", window_size=(400, 800))
            print("window closed")
        else:
            print("no display found, retrying...")
            time.sleep(5)

    client.close()
