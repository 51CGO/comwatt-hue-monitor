#!/usr/bin/python3

import argparse
import datetime
import json
import logging
import logging.handlers
import signal
import time
import threading
import traceback

import comwatt_client
import pythonhuecontrol.v1.bridge
import sunshine_trigger

RETRY_NUMBER = 10


class Monitor(threading.Thread):

    def __init__(
            self,
            comwatt_email, comwatt_password,
            hue_bridge_hostname, hue_key, hue_light_name,
            threshold_production_min=50):

        threading.Thread.__init__(self)

        self.logger = logging.getLogger(self.__class__.__name__)

        # Comwatt credentials
        self.comwatt_email = comwatt_email
        self.comwatt_password = comwatt_password

        # Philips Hue
        self.hue_bridge_hostname = hue_bridge_hostname
        self.hue_key = hue_key
        self.hue_light_name = hue_light_name

        # Sun threshold
        self.threshold_production_min = threshold_production_min

        # Thresolds and colors configuration
        self.thresholds = []

        # Internal objects
        self.hue_bridge = None
        self.hue_client = None
        self.hue_light = None
        self.comwatt_client = None

        self.current_color = None

        # Ready to go !
        self.do_run = True

    def wait(self, seconds):

        time_now = time.time()
        time_end = time_now + seconds

        self.logger.debug("Will wait until %s" % time_end)

        while self.do_run and time_now < time_end:
            self.logger.debug("Time now : %s" % time_now)
            time_now = time.time()
            time.sleep(1)

    def initialize_hue_light(self):

        # Initialize bridge connection
        self.hue_bridge = pythonhuecontrol.v1.bridge.Bridge(
            self.hue_bridge_hostname,
            "http://" + self.hue_bridge_hostname + "/api/" + self.hue_key
        )

        # Find the specified light
        for light_id in self.hue_bridge.light_ids:
            light = self.hue_bridge.light(light_id)

            if light.name == self.hue_light_name:
                self.hue_light = light
                break

    def set_color(self, color=None):

        # Next state = Light on
        if color:

            # No change
            if color == self.current_color:
                return

            self.logger.info("Set color: %s" % color)
            self.hue_light.set_hex_color(color)

            # Light is off => switch on
            if not self.current_color:
                self.logger.info("Switch on")
                self.hue_light.switch_on()

        # Next state = Light off
        else:

            if self.current_color:
                self.logger.info("Switch off")
                self.hue_light.switch_off()

        self.current_color = color

    def initialize_comwatt_client(self):

        # Create a Comwatt client instance
        self.comwatt_client = comwatt_client.ComwattClient()

        # Authenticate the user
        self.comwatt_client.authenticate(
            self.comwatt_email, self.comwatt_password
        )
        sites = self.comwatt_client.get_sites()
        self.site_id = sites[0]['id']

    def retrieve_comwatt_data(self):

        timestamp = None
        production = None
        consumption = None

        if not self.comwatt_client:
            self.initialize_comwatt_client()

        retry_count = 0

        while self.do_run and retry_count <= RETRY_NUMBER:

            try:
                data = self.comwatt_client.get_site_networks_ts_time_ago(
                    self.site_id, aggregation_level="NONE")
                break

            except Exception:

                if retry_count:
                    delay = 2**retry_count
                    self.logger.error(
                        "Unable to retrieve Comwatt data."
                        " Will retry in %d seconds" % delay
                    )
                    self.wait(delay)
                else:
                    self.logger.error(
                        "Unable to retrieve Comwatt data. Will retry now")
                retry_count += 1
                self.initialize_comwatt_client()

        timestamp = data['timestamps'][-1]
        production = data['productions'][-1]
        consumption = data['consumptions'][-1]

        return timestamp, production, consumption

    def run(self):

        try:
            self.logger.info("Run")

            self.initialize_hue_light()
            if self.hue_light is None:
                self.logger.critical(
                    "Unable to find a Hue light named %s" % self.hue_light_name
                )
                return

            dt_now = datetime.datetime.now(datetime.UTC)

            while self.do_run:

                timestamp, production, consumption = (
                    self.retrieve_comwatt_data()
                )

                if type(production) is str:
                    self.logger.warning("Production: %s" % production)
                    time.sleep(2)
                    continue

                if type(consumption) is str:
                    self.logger.warning("Consumption: %s" % consumption)
                    time.sleep(2)
                    continue

                delta = production - consumption

                if production < self.threshold_production_min:
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

        except Exception:
            self.logger.critical(traceback.format_exc())

    def join(self):

        self.logger.info("End")
        self.do_run = False
        self.set_color(None)
        threading.Thread.join(self)


class SunshineThreadManager(sunshine_trigger.SunshineTrigger):

    def __init__(self, latitude, longitude, comwatt_hue_monitor):
        sunshine_trigger.SunshineTrigger.__init__(self, latitude, longitude)
        self.comwatt_hue_monitor = comwatt_hue_monitor

    def on_sunrise(self):

        if self.comwatt_hue_monitor.is_alive():
            self.logger.warning("Monitor is already started")
        else:
            self.comwatt_hue_monitor.start()

        sunshine_trigger.SunshineTrigger.on_sunrise()

    def on_sunset(self):

        self.comwatt_hue_monitor.join()
        sunshine_trigger.SunshineTrigger.on_sunset()

    def join(self):
        self.comwatt_hue_monitor.join()
        sunshine_trigger.SunshineTrigger.join(self)

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--log-file")
    parser.add_argument(
        "--log-level", default="WARN",
        choices=["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]
    )
    args = parser.parse_args()

    if args.log_file:
        log_handler = logging.handlers.RotatingFileHandler(
            filename=args.log_file, mode="a",
            maxBytes=1024 * 1024, backupCount=5)
        logging.basicConfig(
            format="%(asctime)s %(levelname)s %(message)s",
            level=args.log_level, handlers=[log_handler])
    else:
        logging.basicConfig(
            format="%(asctime)s %(levelname)s %(message)s",
            level=args.log_level
        )

    fd = open(args.config)
    dict_config = json.load(fd)
    fd.close()

    config_comwatt_email = dict_config["comwatt"]["email"]
    config_comwatt_password = dict_config["comwatt"]["password"]

    config_hue_bridge = dict_config["hue"]["bridge"]
    config_hue_key = dict_config["hue"]["key"]
    config_hue_light = dict_config["hue"]["light"]

    config_threshold_production_min = dict_config["thresholds"]["sun"]["min"]

    config_list_thresholds = [v for v in dict_config["thresholds"]["delta"]]

    config_latitude = dict_config["location"]["latitude"]
    config_longitude = dict_config["location"]["longitude"]

    m = Monitor(
        config_comwatt_email, config_comwatt_password,
        config_hue_bridge, config_hue_key, config_hue_light,
        config_threshold_production_min
    )

    m.thresholds = config_list_thresholds

    m.start()

    s = SunshineThreadManager(config_latitude, config_longitude, m)

    signal.signal(signal.SIGTERM, s.join)

    s.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        s.join()
