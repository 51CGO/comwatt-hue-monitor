#!/usr/bin/python3

import argparse
import datetime
import json
import logging
import logging.handlers
import signal
import sys
import time
import traceback

import comwatt_client

import pythonhuecontrol.v1.bridge


class Monitor(object):

    def __init__(
            self, 
            comwatt_email=None, comwatt_password=None, 
            hue_bridge=None, hue_key=None, hue_light=None,
            headless=True):

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

        # Browser options
        self.headless = headless

        # Thresolds and colors configuration
        self.thresholds = []

        # Internal objects
        self.bridge = None
        self.client = None
        self.sun_tool = None
        self.light_monitor = None

        self.logger = logging.getLogger("Monitor")
        
        self.previous_state = -1000000000
        self.same_state_count = 0

    def initialize(self):

        # Initialize bridge connection
        self.bridge = pythonhuecontrol.v1.bridge.Bridge(self.hue_bridge, "http://" + self.hue_bridge + "/api/" + self.hue_key)

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

        list_thresholds = [ v for v in config["thresholds"]["delta"] ]

        for key in list_thresholds:
            color = config["thresholds"]["delta"][key]

            self.thresholds.append((int(key), color))


    def stop(self, signum, frame):
        self.logger.info("Stop")
        self.do_run = False

    def run(self, count=0, delay=5):

        self.logger.info("Run")

        signal.signal(signal.SIGTERM, self.stop)

        #self.sun_tool = suntime.Sun(config["location"]["latitude"], config["location"]["longitude"])
        
        # Create a Comwatt client instance
        self.client = comwatt_client.ComwattClient()

        # Authenticate the user
        self.client.authenticate(self.comwatt_email, self.comwatt_password)
        sites = self.client.get_sites()
        self.site_id = sites[0]['id']

        count = 0

        dt_now = datetime.datetime.now(datetime.UTC)

        while self.do_run:
            
            self.logger.info(" Loop ".center(10, "="))
            
            try:
                
                data = self.client.get_site_networks_ts_time_ago(self.site_id, aggregation_level="NONE")

                timestamp = data['timestamps'][-1]
                production = data['productions'][-1]
                consumption = data['consumptions'][-1]
                delta = production - consumption
                

                if production < self.threshold_sun : 
                    # Sun is not sufficient -> Off
                    #TODO : Optimiser les appels API (mémoriser létat de la lampe)
                    self.light_monitor.switch_off()

                else:
                        
                        color = None
                        i = 0
                        while i < len(self.thresholds):
                            if delta > self.thresholds[i][0]:
                                color = self.thresholds[i][1]
                            else:
                                break
                            i += 1

                        #TODO : Optimiser les appels API (mémoriser létat de la lampe)
                        self.light_monitor.switch_on()
                        self.light_monitor.set_hex_color(color)  

                dt_ts = datetime.datetime.fromisoformat(timestamp)
                
                dt_next = dt_ts + datetime.timedelta(seconds=122)

                if dt_next < dt_now:
                    dt_next = dt_now + datetime.timedelta(seconds=2)
            
                self.logger.info(
                    "T=%s P=%6d C=%6d D=%6d N=%s (%s)" 
                    %
                    (timestamp,
                    production,
                    consumption,
                    delta,
                    dt_next,
                    color)
                    )

                while(dt_now < dt_next):

                    dt_now = datetime.datetime.now(datetime.UTC)
                    time.sleep(1)

            except:
                traceback.print_exc()
                self.logger.fatal(traceback.format_exc)
                sys.exit(1)

            if args.count :

                count += 1

                if count >= args.count:
                    break


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--delay", type=int, default=1)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--log-file")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
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
        log_handler = logging.handlers.RotatingFileHandler(filename=args.log_file, mode="a", maxBytes=1024 * 1024, backupCount=5)
        logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=log_level, handlers=[log_handler])
    else:
        logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=log_level)


    fd = open(args.config)
    config = json.load(fd)
    fd.close()

    m = Monitor(headless=not args.show_browser)
    m.load_configuration(config)
    m.initialize()
    try:
        m.run(delay=args.delay)
    except:
        traceback.print_exc()
        logging.fatal(traceback.format_exc())
