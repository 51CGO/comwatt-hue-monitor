#!/usr/bin/python3

import argparse
import datetime
import json
import logging
import logging.handlers
import time
import threading
import traceback

import comwatt_client

import pythonhuecontrol.v1.bridge


class Monitor(threading.Thread):

    def __init__(
            self,
            comwatt_email=None, comwatt_password=None,
            hue_bridge=None, hue_key=None, hue_light=None):

        threading.Thread.__init__(self)

        # Comwatt credentials
        self.comwatt_email = comwatt_email
        self.comwatt_password = comwatt_password

        # Philips Hue
        self.hue_bridge = hue_bridge
        self.hue_key = hue_key
        self.hue_light = hue_light

        # Location
        self.latitude = 0
        self.longitude = 0

        # Sun threshold
        self.threshold_sun = -1000000000

        # Thresolds and colors configuration
        self.thresholds = []

        # Internal objects
        self.bridge = None
        self.client = None
        self.light_monitor = None

        self.logger = logging.getLogger("Monitor")

        self.current_color = None

    def initialize(self):

        # Initialize bridge connection
        self.bridge = pythonhuecontrol.v1.bridge.Bridge(
            self.hue_bridge,
            "http://" + self.hue_bridge + "/api/" + self.hue_key
        )

        # Find the specified light
        for light_id in self.bridge.light_ids:
            light = self.bridge.light(light_id)

            if light.name == self.hue_light:
                self.light_monitor = light
                break

        assert self.light_monitor is not None

        # Ready to go !
        self.do_run = True

    def load_configuration(self, config):

        self.comwatt_email = config["comwatt"]["email"]
        self.comwatt_password = config["comwatt"]["password"]

        self.hue_bridge = config["hue"]["bridge"]
        self.hue_key = config["hue"]["key"]
        self.hue_light = config["hue"]["light"]

        self.threshold_sun = config["thresholds"]["sun"]["min"]

        list_thresholds = [v for v in config["thresholds"]["delta"]]

        for key in list_thresholds:
            color = config["thresholds"]["delta"][key]

            self.thresholds.append((int(key), color))

    def set_color(self, color=None):

        # Next state = Light on
        if color:

            # No change
            if color == self.current_color:
                return

            self.logger.info("Set color: %s" % color)
            self.light_monitor.set_hex_color(color)

            # Light is off => switch on
            if not self.current_color:
                self.logger.info("Switch on")
                self.light_monitor.switch_on()

        # Next state = Light off
        else:

            if self.current_color:
                self.logger.info("Switch off")
                self.light_monitor.switch_off()

        self.current_color = color

    def run(self):

        self.logger.info("Run")

        # Create a Comwatt client instance
        self.client = comwatt_client.ComwattClient()

        # Authenticate the user
        self.client.authenticate(self.comwatt_email, self.comwatt_password)
        sites = self.client.get_sites()
        self.site_id = sites[0]['id']

        dt_now = datetime.datetime.now(datetime.UTC)

        while self.do_run:

            data = self.client.get_site_networks_ts_time_ago(
                self.site_id, aggregation_level="NONE")

            timestamp = data['timestamps'][-1]
            production = data['productions'][-1]
            consumption = data['consumptions'][-1]

            if type(production) is str:
                self.logger.warning("Production: %s" % production)
                time.sleep(2)
                continue

            if type(consumption) is str:
                self.logger.warning("Consumption: %s" % consumption)
                time.sleep(2)
                continue

            delta = production - consumption

            if production < self.threshold_sun:
                # Sun is not sufficient -> Off
                self.set_color(None)

            else:

                color = None
                i = 0
                while i < len(self.thresholds):
                    if delta > self.thresholds[i][0]:
                        color = self.thresholds[i][1]
                    else:
                        break
                    i += 1

                self.set_color(color)

            dt_ts = datetime.datetime.fromisoformat(timestamp)

            dt_next = dt_ts + datetime.timedelta(seconds=122)

            if dt_next < dt_now:
                dt_next = dt_now + datetime.timedelta(seconds=2)

            self.logger.info(
                "T=%s P=%6d C=%6d D=%6d N=%s (%s)"
                % (
                    dt_ts.strftime("%H:%M:%S"),
                    production,
                    consumption,
                    delta,
                    dt_next.strftime("%H:%M:%S"),
                    color
                )
            )

            while self.do_run and dt_now < dt_next:

                dt_now = datetime.datetime.now(datetime.UTC)
                time.sleep(1)

    def join(self):

        self.logger.info("End")
        self.do_run = False
        threading.Thread.join(self)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--log-file")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    )
    args = parser.parse_args()

    if not args.log_level or args.log_level == "ERROR":
        log_level = logging.ERROR
    if args.log_level == "DEBUG":
        log_level = logging.DEBUG
    else:
        if args.log_level == "INFO":
            log_level = logging.INFO
        else:
            if args.log_level == "WARNING":
                log_level = logging.WARN

    if args.log_file:
        log_handler = logging.handlers.RotatingFileHandler(
            filename=args.log_file, mode="a",
            maxBytes=1024 * 1024, backupCount=5)
        logging.basicConfig(
            format="%(asctime)s %(levelname)s %(message)s",
            level=log_level, handlers=[log_handler])
    else:
        logging.basicConfig(
            format="%(asctime)s %(levelname)s %(message)s", level=log_level)

    fd = open(args.config)
    config = json.load(fd)
    fd.close()

    m = Monitor()
    m.load_configuration(config)
    m.initialize()
    m.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        m.join()
