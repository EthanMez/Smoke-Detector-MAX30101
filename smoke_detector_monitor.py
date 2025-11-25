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

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('smoke_detector.log'),
        logging.StreamHandler()
    ]
)

#sys.path.insert(0, '/home/ops/cpx400dp')
#import cpx400dp

class SmokeDetectorMonitor:
    def __init__(self, arduino_port="/dev/ttyUSB1", db_path="smoke_detector.db"):
        # Configuration
        self.arduino_port = arduino_port
        self.db_path = db_path
        self.calculation_interval = 3 * 60  # 3 minutes
        
        # Initialize components
        self.arduino_serial = None
        self.setup_database()
        
        # Data storage
        self.saved_values = {'R': [], 'G': [], 'IR': []}
        self.means = {'R': None, 'G': None, 'IR': None}
        self.sds = {'R': None, 'G': None, 'IR': None}
        self.last_calculation_time = time.time()
        
        # Load settings
        self.settings = self.load_settings()
        
    def setup_database(self):
        """Initialize SQLite database for data storage"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                R INTEGER,
                G INTEGER,
                IR INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                R_mean REAL,
                R_std REAL,
                G_mean REAL,
                G_std REAL,
                IR_mean REAL,
                IR_std REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
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
    
    def connect_arduino(self):
        """Connect to Arduino"""
        try:
            if self.arduino_serial:
                self.arduino_serial.close()
            self.arduino_serial = serial.Serial(self.arduino_port, 115200, timeout=1)
            logging.info("Connected to Arduino")
            return True
        except Exception as e:
            logging.error(f"Failed to connect to Arduino: {e}")
            return False
    
    def read_smoke_detector(self):
        """Read values from Arduino smoke detector"""
        if not self.arduino_serial:
            return {}
            
        try:
            input1 = self.arduino_serial.readline().decode().strip()
            inputs = input1.split(';')
            values = {}
            for input_str in inputs:
                value = input_str.split(":")
                if len(value) == 2 and value[0] in ['R', 'G', 'IR']:
                    try:
                        val = int(value[1])
                        if val > 0:
                            values[value[0]] = val
                    except ValueError:
                        continue
            ### REMOVE RAW ###
            return values, input1
            ### REMOVE RAW ###
        except Exception as e:
            ### REMOVE RAW ###
            #input1 = self.arduino_serial.readline().decode().strip()
            logging.error(f"Error reading from Arduino: {e}, RAW: {input1}")
            ### REMOVE RAW ###
            return {}
    
    def save_reading(self, values):
        """Save reading to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO readings (R, G, IR) VALUES (?, ?, ?)
        ''', (values.get('R'), values.get('G'), values.get('IR')))
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
            logging.info(f"Retention policy applied: {deleted} old readings deleted (>{retention_days} days old).")
        
    def calculate_statistics(self):
        """Calculate and save statistics"""
        for light_type in self.saved_values.keys():
            if len(self.saved_values[light_type]) > 0:
                self.means[light_type] = np.nanmean(self.saved_values[light_type])
                self.sds[light_type] = np.nanstd(self.saved_values[light_type])
                self.saved_values[light_type] = []
        
        # Save to database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO statistics (R_mean, R_std, G_mean, G_std, IR_mean, IR_std) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (self.means['R'], self.sds['R'], self.means['G'], 
              self.sds['G'], self.means['IR'], self.sds['IR']))
        conn.commit()
        conn.close()
        
        logging.info(f"Statistics updated: R({self.means['R']:.2f}±{self.sds['R']:.2f}), "
                    f"G({self.means['G']:.2f}±{self.sds['G']:.2f}), "
                    f"IR({self.means['IR']:.2f}±{self.sds['IR']:.2f})")
        
        # Run retention policy (once per statistics cycle = every 3 min)
        self.cleanup_old_readings(retention_days=30)
    
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
            
            logging.info(f"Email sent to {recipients}: {subject}")
            return recipients
        except Exception as e:
            logging.error(f"Failed to send email: {e}")
            return []
    
    def shutdown_power_supply(self):
        """Shutdown power supply"""
        try:
            # Uncomment these lines for actual power supply control
            # power_supply_serial = serial.Serial('/dev/ttyACM1')
            # cpx400dp.switchOff(power_supply_serial, channel=1)
            # cpx400dp.switchOff(power_supply_serial, channel=2)
            # power_supply_serial.close()
            
            logging.critical("POWER SUPPLY SHUTDOWN INITIATED")
            return True
        except Exception as e:
            logging.error(f"Failed to shutdown power supply: {e}")
            return False
    
    def calculate_z_scores(self, values):
        """Calculate z-scores"""
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
            INSERT INTO alerts (alert_type, message, R_value, G_value, IR_value, 
                              R_zscore, G_zscore, IR_zscore) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (alert_type, message, values.get('R'), values.get('G'), values.get('IR'),
              z_scores.get('R'), z_scores.get('G'), z_scores.get('IR')))
        conn.commit()
        conn.close()
    
    ### REMOVE RAW ###
    def check_alerts(self, values, raw):
    ### REMOVE RAW ###
        """Check for alert conditions"""
        if None in self.means.values() or None in self.sds.values():
            return
        
        z_scores = self.calculate_z_scores(values)
        conditions = {}
        
        for key in ['R', 'G', 'IR']:
            if key in z_scores:
                conditions[key] = abs(z_scores[key]) > 5 # only 5 sigma deviation will trigger alerts
        
        # WARNING - any sensor triggered
        if any(conditions.values()):
            message = f'Concerning smoke levels detected'
            self.save_alert('WARNING', message, values, z_scores)
            
            warning_message = (f'Concerning smoke levels have been detected in the clean room. The burn-in has NOT been stopped.\n\n'
                             f'RED values are {z_scores.get("R", np.nan):.2f} standard deviations from the mean.\n'
                             f'GREEN values are {z_scores.get("G", np.nan):.2f} standard deviations from the mean.\n'
                             f'IR values are {z_scores.get("IR", np.nan):.2f} standard deviations from the mean.')

            self.send_email(warning_message, 'SMOKE LEVEL WARNING', priority='2')
            ### REMOVE RAW ###
            logging.warning(f"SMOKE WARNING: {values} | Z-scores: {z_scores} | RAW: {raw}")
            ### REMOVE RAW ###
        
        # CRITICAL - all sensors triggered
        if all(conditions.get(key, False) for key in ['R', 'G', 'IR']):
            message = 'DANGEROUS smoke levels - Burn-in stopped!'
            self.save_alert('CRITICAL', message, values, z_scores)
            
            stop_message = (f'Dangerous smoke levels have been detected in the clean room.\n\n'
                          f'RED values are {z_scores.get("R", np.nan):.2f} standard deviations from the mean.\n'
                          f'GREEN values are {z_scores.get("G", np.nan):.2f} standard deviations from the mean.\n'
                          f'IR values are {z_scores.get("IR", np.nan):.2f} standard deviations from the mean.\n'
                          f'The burn-in has been stopped automatically.')

            self.send_email(stop_message, 'BURN-IN STOPPED - CRITICAL ALERT', priority='1')

            if self.settings.get('auto_shutdown_enabled') == 'true':
                #self.shutdown_power_supply()
                # Stop monitoring after shutdown
                self.update_setting('monitoring_active', 'false')

            ### REMOVE RAW ###
            logging.critical(f"CRITICAL SMOKE ALERT: {values} | Z-scores: {z_scores} | RAW: {raw}")
            ### REMOVE RAW ###

    def run(self):
        """Main monitoring loop"""
        logging.info("Starting smoke detector monitoring...")
        
        if not self.connect_arduino():
            logging.error("Failed to connect to Arduino. Exiting.")
            return
        
        self.update_setting('monitoring_active', 'true')
        
        try:
            while self.settings.get('monitoring_active') == 'true':
                # Reload settings periodically
                self.settings = self.load_settings()
                
                # Read values
                ### REMOVE RAW ###
                values, raw = self.read_smoke_detector()
                ### REMOVE RAW ###
                
                if len(values) > 0:
                    # Save reading
                    self.save_reading(values)
                    
                    # Update saved values for statistics
                    for key in ['R', 'G', 'IR']:
                        if key in values:
                            self.saved_values[key].append(values[key])
                        else:
                            self.saved_values[key].append(np.nan)
                    
                    # Calculate statistics periodically
                    if time.time() - self.last_calculation_time >= self.calculation_interval:
                        self.calculate_statistics()
                        self.last_calculation_time = time.time()
                    
                    # Check for alerts (skip if not calibrated)
                    if None not in self.means.values() and None not in self.sds.values():
                        ### REMOVE RAW ###
                        self.check_alerts(values, raw)
                        ### REMOVE RAW ###
                    else:
                        remaining_time = self.calculation_interval - (time.time() - self.last_calculation_time)
                        logging.info(f'Calibrating... Time remaining: {remaining_time:.0f}s')
                
                time.sleep(1)  # 1 second between readings
                
        except KeyboardInterrupt:
            logging.info("Monitoring stopped by user")
        except Exception as e:
            logging.error(f"Monitoring error: {e}")
        finally:
            if self.arduino_serial:
                self.arduino_serial.close()
            self.update_setting('monitoring_active', 'false')
            logging.info("Monitoring stopped")

if __name__ == "__main__":
    monitor = SmokeDetectorMonitor()
    monitor.run()