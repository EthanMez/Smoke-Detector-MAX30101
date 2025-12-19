import numpy as np
import time
import sys
import serial
import smtplib
from email.mime.text import MIMEText
import json
import sqlite3
from datetime import datetime
import logging
import os

class SmokeDetectorChannel:
    """Manages data and operations for a single smoke detector channel"""
    
    def __init__(self, atlaspc, channel_number, db_path, settings):
        self.atlaspc = atlaspc
        self.channel = channel_number
        self.db_path = db_path
        self.settings = settings
        self.calculation_interval = 3 * 60  # 3 minutes
        
        # Data storage
        self.saved_values = {'R': [], 'G': [], 'IR': []}
        self.means = {'R': None, 'G': None, 'IR': None}
        self.sds = {'R': None, 'G': None, 'IR': None}
        self.last_calculation_time = time.time()
        
        # Set up channel-specific logger
        self.logger = self._setup_logger()
        self.logger.info(f"Channel {self.channel} for atlaspc{self.atlaspc} initialized")
        
    def _setup_logger(self):
        """Set up logger for this channel"""
        logger = logging.getLogger(f'atlaspc{self.atlaspc}_ch{self.channel}')

        # Set minimum severity level to INFO
        logger.setLevel(logging.INFO) 
        
        # Clear any existing handlers to prevent duplicate logs
        logger.handlers = []
        
        # Create file handler for this channel
        fh = logging.FileHandler(f'smoke_detector_atlaspc{self.atlaspc}_ch{self.channel}.log')
        fh.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        
        logger.addHandler(fh)
        return logger
    
    def add_reading(self, values):
        """Add a reading to the saved values"""
        for key in ['R', 'G', 'IR']:
            if key in values:
                self.saved_values[key].append(values[key])
            else:
                self.saved_values[key].append(np.nan)
    
    def should_calculate_statistics(self):
        """Check if it's time to calculate statistics"""
        return time.time() - self.last_calculation_time >= self.calculation_interval
    
    def calculate_statistics(self):
        """Calculate and save statistics for this channel"""
        for light_type in self.saved_values.keys():
            if len(self.saved_values[light_type]) > 0:
                self.means[light_type] = np.nanmean(self.saved_values[light_type])
                self.sds[light_type] = np.nanstd(self.saved_values[light_type])
                self.saved_values[light_type] = []
        
        # Save to database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO statistics (atlaspc, channel, R_mean, R_std, G_mean, G_std, IR_mean, IR_std) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (self.atlaspc, self.channel, self.means['R'], self.sds['R'], 
              self.means['G'], self.sds['G'], 
              self.means['IR'], self.sds['IR']))
        conn.commit()
        conn.close()
        
        self.logger.info(f"Statistics updated: R({self.means['R']:.2f}±{self.sds['R']:.2f}), "
                        f"G({self.means['G']:.2f}±{self.sds['G']:.2f}), "
                        f"IR({self.means['IR']:.2f}±{self.sds['IR']:.2f})")
        
        self.last_calculation_time = time.time()
    
    def is_calibrated(self):
        """Check if channel has been calibrated"""
        return None not in self.means.values() and None not in self.sds.values()
    
    def get_remaining_calibration_time(self):
        """Get remaining time for calibration"""
        return self.calculation_interval - (time.time() - self.last_calculation_time)
    
    def calculate_z_scores(self, values):
        """Calculate z-scores for current values"""
        z_scores = {}
        for key in ['R', 'G', 'IR']:
            if (key in values and self.means[key] is not None 
                and self.sds[key] is not None and self.sds[key] != 0):
                z_scores[key] = (values[key] - self.means[key]) / self.sds[key]
        return z_scores
    
    def save_alert(self, alert_type, message, values, z_scores):
        """Save alert to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO alerts (atlaspc, channel, alert_type, message, R_value, G_value, IR_value, 
                              R_zscore, G_zscore, IR_zscore) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (self.atlaspc, self.channel, alert_type, message, values.get('R'), values.get('G'), values.get('IR'),
              z_scores.get('R'), z_scores.get('G'), z_scores.get('IR')))
        conn.commit()
        conn.close()
    
    def send_email(self, message, subject, priority='3'):
        """Send email notification"""
        if self.settings.get('email_enabled') != 'true':
            return []
            
        try:
            sender = "no-reply@lps.umontreal.ca"
            recipients = self.settings.get('email_recipients', '').split(',')
            recipients = [r.strip() for r in recipients if r.strip()]
            
            msg = MIMEText(message)
            msg['Subject'] = subject
            msg['From'] = sender
            msg['To'] = ', '.join(recipients)
            msg['X-Priority'] = priority
            
            s = smtplib.SMTP('localhost')
            s.sendmail(sender, recipients, msg.as_string())
            s.quit()
            
            self.logger.info(f"Email sent to {recipients}: {subject}")
            return recipients
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return []
    
    def shutdown_power_supply(self):
        """Shutdown power supply for this channel"""
        try:
            # Uncomment these lines for actual power supply control
            # power_supply_serial = serial.Serial('/dev/ttyACM1')
            # cpx400dp.switchOff(power_supply_serial, channel=self.channel)
            # power_supply_serial.close()
            
            self.logger.critical(f"POWER SUPPLY SHUTDOWN INITIATED FOR ATLASPC{self.atlaspc} (CHANNEL {self.channel})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to shutdown power supply: {e}")
            return False
    
    def check_alerts(self, values):
        """Check for alert conditions and take appropriate action"""
        if not self.is_calibrated():
            return
        
        z_scores = self.calculate_z_scores(values)
        conditions = {}
        
        for key in ['R', 'G', 'IR']:
            if key in z_scores:
                conditions[key] = abs(z_scores[key]) > 5  # only 5 sigma deviation will trigger alerts
        
        # WARNING - any sensor triggered
        if any(conditions.values()):
            message = f'Concerning smoke levels detected on atlaspc{self.atlaspc}'
            self.save_alert('WARNING', message, values, z_scores)
            
            warning_message = (f'Concerning smoke levels have been detected in the clean room on atlaspc{self.atlaspc}. '
                             f'The burn-in has NOT been stopped.\n\n'
                             f'RED values are {z_scores.get("R", np.nan):.2f} standard deviations from the mean.\n'
                             f'GREEN values are {z_scores.get("G", np.nan):.2f} standard deviations from the mean.\n'
                             f'IR values are {z_scores.get("IR", np.nan):.2f} standard deviations from the mean.')

            self.send_email(warning_message, f'SMOKE LEVEL WARNING - atlaspc{self.atlaspc}', priority='2')
            self.logger.warning(f"SMOKE WARNING: {values} | Z-scores: {z_scores}")
        
        # CRITICAL - all sensors triggered
        if all(conditions.get(key, False) for key in ['R', 'G', 'IR']):
            message = f'DANGEROUS smoke levels on atlaspc{self.atlaspc} - Burn-in stopped!'
            self.save_alert('CRITICAL', message, values, z_scores)
            
            stop_message = (f'Dangerous smoke levels have been detected in the clean room on atlaspc{self.atlaspc}.\n\n'
                          f'RED values are {z_scores.get("R", np.nan):.2f} standard deviations from the mean.\n'
                          f'GREEN values are {z_scores.get("G", np.nan):.2f} standard deviations from the mean.\n'
                          f'IR values are {z_scores.get("IR", np.nan):.2f} standard deviations from the mean.\n'
                          f'The burn-in has been stopped automatically for this channel.')

            self.send_email(stop_message, f'BURN-IN STOPPED - CRITICAL ALERT - ATLASPC{self.atlaspc}', priority='1')

            if self.settings.get('auto_shutdown_enabled') == 'true':
                self.shutdown_power_supply()

            self.logger.critical(f"CRITICAL SMOKE ALERT: {values} | Z-scores: {z_scores}")


class SmokeDetectorMonitor:
    """Main monitor that coordinates multiple smoke detector channels"""
    
    def __init__(self, arduino_port="/dev/cu.usbmodem101", db_path="smoke_detector.db"):
        self.arduino_port = arduino_port
        self.db_path = db_path
        self.arduino_serial = None
        self.restart_time = time.time() + 10*3600  # Restart every 10 hours
        
        # Initialize database
        self.setup_database()
        
        # Load settings
        self.settings = self.load_settings()
        
        # Dictionary to store channel objects
        self.channels = {}
        self.atlaspc_channel_map = {
            1: 20, # channel 1 -> atlaspc20
            2: 21, # channel 2 -> atlaspc21
            3: 22, # channel 3 -> atlaspc22
        }
        
    def setup_database(self):
        """Initialize SQLite database for data storage"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create tables with channel field
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                atlaspc INTEGER NOT NULL,
                channel INTEGER NOT NULL,
                R INTEGER,
                G INTEGER,
                IR INTEGER
            )
        ''')
        
        # Create index for faster channel-based queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_atlaspc_timestamp 
            ON readings(atlaspc, timestamp)
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                atlaspc INTEGER NOT NULL,
                channel INTEGER NOT NULL,
                R_mean REAL,
                R_std REAL,
                G_mean REAL,
                G_std REAL,
                IR_mean REAL,
                IR_std REAL
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_stats_atlaspc_timestamp 
            ON statistics(atlaspc, timestamp)
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                atlaspc INTEGER NOT NULL,
                channel INTEGER NOT NULL,
                alert_type TEXT,
                message TEXT,
                R_value INTEGER,
                G_value INTEGER,
                IR_value INTEGER,
                R_zscore REAL,
                G_zscore REAL,
                IR_zscore REAL
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_alerts_atlaspc_timestamp 
            ON alerts(atlaspc, timestamp)
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        
    def load_settings(self):
        """Load settings from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT key, value FROM settings')
        settings = dict(cursor.fetchall())
        conn.close()
        
        # Default settings
        defaults = {
            'email_enabled': 'false',
            'auto_shutdown_enabled': 'false',
            'email_recipients': 'ethan.meszaros@umontreal.ca',
            'monitoring_active': 'false'
        }
        
        for key, value in defaults.items():
            if key not in settings:
                self.update_setting(key, value)
                settings[key] = value
                
        return settings
    
    def update_setting(self, key, value):
        """Update a setting in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()
        if not hasattr(self, "settings"):
            self.settings = {}
        self.settings[key] = value
    
    def get_or_create_channel(self, atlaspc, channel_number):
        """Get existing channel or create new one"""
        if channel_number not in self.channels:
            self.channels[channel_number] = SmokeDetectorChannel(atlaspc, channel_number, self.db_path, self.settings)
        return self.channels[channel_number]
    
    def connect_arduino(self):
        """Connect to Arduino"""
        try:
            if self.arduino_serial:
                self.arduino_serial.close()
            self.arduino_serial = serial.Serial(self.arduino_port, 115200, timeout=1)
            print("Connected to Arduino")
            return True
        except Exception as e:
            print(f"Failed to connect to Arduino: {e}")
            return False
        
    def parse_line(self, line):
        """Parse a line from Arduino output"""
        try:
            parts = [p.strip() for p in line.split(";")]

            if len(parts) < 5 or "CH" not in parts[0]:
                return {}
            
            if any(x not in line for x in ['CH', 'R', 'G', 'IR']):
                raise ValueError("Incomplete data from sensor")
            
            ch_label, ch_value = parts[0].split(':')
            R_label, R_value = parts[1].split(':')
            IR_label, IR_value = parts[2].split(':')
            G_label, G_value = parts[3].split(':')
            
            return {
                ch_label: int(ch_value),
                R_label: int(R_value),
                IR_label: int(IR_value),
                G_label: int(G_value),
            }
        except Exception as e:
            print(f"Error parsing line: {e}")
            return {}
    
    def read_smoke_detector(self):
        """Read values from Arduino smoke detector"""
        if not self.arduino_serial:
            return {}
            
        try:
            arduino_readout = self.arduino_serial.readline().decode("utf-8", errors="ignore").strip()

            # Log which ports have sensors connected
            if arduino_readout.startswith("STATUS"):
                ch, present = arduino_readout.split(";")[2], arduino_readout.split(";")[4]
                if str(present)=='yes': 
                    print(f"A sensor is connected to channel: {ch}")

            return self.parse_line(arduino_readout)
        except Exception as e:
            print(f"Error reading from Arduino: {e}")
            return {}
    
    def save_reading(self, atlaspc, channel, values):
        """Save reading to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO readings (atlaspc, channel, R, G, IR) VALUES (?, ?, ?, ?, ?)
        ''', (atlaspc, channel, values.get('R'), values.get('G'), values.get('IR')))
        conn.commit()
        conn.close()

    def cleanup_old_readings(self, retention_days=30):
        """Delete readings older than retention_days from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM readings
            WHERE timestamp < datetime('now', ?)
        ''', (f'-{retention_days} days',))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
    
        if deleted > 0:
            print(f"Retention policy applied: {deleted} old readings deleted (>{retention_days} days old).")

    def run(self):
        """Main monitoring loop"""
        print("Starting smoke detector monitoring...")
        
        if not self.connect_arduino():
            print("Failed to connect to Arduino. Exiting.")
            return
        
        self.update_setting('monitoring_active', 'true')
        
        try:
            while self.settings.get('monitoring_active') == 'true':
                
                # Check for scheduled restart
                if time.time() >= self.restart_time:
                    print("Restarting monitoring script to prevent error excess.")
                    if self.arduino_serial:
                        self.arduino_serial.close()
                        self.update_setting('monitoring_active', 'false')
                        
                        # Restart the script
                        os.execv(sys.executable, ['python'] + sys.argv)

                # Reload settings periodically
                self.settings = self.load_settings()
                
                # Update settings for all existing channels
                for channel in self.channels.values():
                    channel.settings = self.settings
                
                # Read values
                values = self.read_smoke_detector()
                
                if len(values) > 0 and 'CH' in values:
                    channel_number = values['CH']

                    try: 
                        atlaspc = self.atlaspc_channel_map[channel_number]
                    except KeyError:
                        raise ValueError(f"Channel {channel_number} is not mapped in an atlaspc.")
                    
                    # Get or create channel
                    channel = self.get_or_create_channel(atlaspc, channel_number)
                    
                    # Save reading
                    self.save_reading(atlaspc, channel_number, values)
                    
                    # Add reading to channel
                    channel.add_reading(values)
                    
                    # Calculate statistics if needed
                    if channel.should_calculate_statistics():
                        channel.calculate_statistics()
                        # Run retention policy periodically
                        self.cleanup_old_readings(retention_days=30)
                    
                    # Check for alerts or log calibration status
                    if channel.is_calibrated():
                        channel.check_alerts(values)
                    else:
                        remaining_time = channel.get_remaining_calibration_time()
                        channel.logger.info(f'Calibrating... Time remaining: {remaining_time:.0f}s')
                
                time.sleep(1)  # 1 second between readings
                
        except KeyboardInterrupt:
            print("Monitoring stopped by user")
        except Exception as e:
            print(f"Monitoring error: {e}")
        finally:
            if self.arduino_serial:
                self.arduino_serial.close()
            self.update_setting('monitoring_active', 'false')
            print("Monitoring stopped")

if __name__ == "__main__":
    monitor = SmokeDetectorMonitor()
    monitor.run()