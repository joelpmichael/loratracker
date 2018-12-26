/*******************************************************************************
 * Copyright (c) 2018 Joel Michael
 * 
 * Based on LMIC.h example code by Thomas Telkamp and Matthijs Kooijman
 * and TinyGPS.h example code by Mikal Hart
 * 
 * This code interfaces with a GPS receiver (using SoftSerial on pins 3,4)
 * and sends GPS co-ordinates via LoRaWAN to the fully autonomous gateway
 * 
 * output is 20 bytes of packed data (5 x 32bit words):
 * long i_lat: decimal latitude millionths - divide by 1,000,000 for decimal
 * long i_lon: decimal longitude millionths
 * long i_alt: cm above sea level - divide by 100 for decimal M
 * u_long gps_date: date stamp of GPS in DDMMYY
 * u_long gps_time: time stamp of GPS in HHMMSSff - divide by 100 for decimal S
 *
 * Tracker uses OTAA (Over-the-air activation), where where a DevEUI and
 * application key is configured, which are used in an over-the-air
 * activation procedure where a DevAddr and session keys are
 * assigned/generated for use with all further communication.
 *
 * To use this sketch, first register your application and device with
 * your loraserver.io gateway, to set or generate a DevEUI and AppKey.
 * Each device has its own DevEUI and AppKey.
 * 
 * Do not forget to define the radio type correctly in config.h.
 *
 *******************************************************************************/

// SoftwareSerial setup
#include <SoftwareSerial.h>
SoftwareSerial SoftSerial(3, 4); // Arduino RX, TX to conenct to GPS module.

// GPS setup
#include <TinyGPS.h>
TinyGPS gps;

// LMIC setup
#include <lmic.h>
#include <hal/hal.h>
#include <SPI.h>

// This EUI must be in little-endian format, so least-significant-byte
// first. When copying an EUI from ttnctl output, this means to reverse
// the bytes. For TTN issued EUIs the last bytes should be 0xD5, 0xB3,
// 0x70.
// loraserver.io gateway needs all 0x00 AppEUI
static const u1_t PROGMEM APPEUI[8]={ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };
void os_getArtEui (u1_t* buf) { memcpy_P(buf, APPEUI, 8);}

// This should also be in little endian format, see above.
// each tracker needs its own DevEUI
static const u1_t PROGMEM DEVEUI[8]={ 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08 };
void os_getDevEui (u1_t* buf) { memcpy_P(buf, DEVEUI, 8);}

// This key should be in big endian format (or, since it is not really a
// number but a block of memory, endianness does not really apply). In
// practice, a key taken from ttnctl can be copied as-is.
// The key shown here is the semtech default key.
// each tracker needs its own AppKey
static const u1_t PROGMEM APPKEY[16] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10 };
void os_getDevKey (u1_t* buf) {  memcpy_P(buf, APPKEY, 16);}

static osjob_t sendjob;

// Schedule TX every this many seconds (might become longer due to duty
// cycle limitations).
const unsigned TX_INTERVAL = 3;

// Pin mapping
const lmic_pinmap lmic_pins = {
    .nss = 10,
    .rxtx = LMIC_UNUSED_PIN,
    .rst = 9,
    .dio = {2, 6, 7},
};

void onEvent (ev_t ev) {
    Serial.print(os_getTime());
    Serial.print(": ");
    switch(ev) {
        case EV_SCAN_TIMEOUT:
            Serial.println(F("EV_SCAN_TIMEOUT"));
            break;
        case EV_BEACON_FOUND:
            Serial.println(F("EV_BEACON_FOUND"));
            break;
        case EV_BEACON_MISSED:
            Serial.println(F("EV_BEACON_MISSED"));
            break;
        case EV_BEACON_TRACKED:
            Serial.println(F("EV_BEACON_TRACKED"));
            break;
        case EV_JOINING:
            Serial.println(F("EV_JOINING"));
            break;
        case EV_JOINED:
            Serial.println(F("EV_JOINED"));

            // Disable link check validation (automatically enabled
            // during join, but not supported by TTN at this time).
            LMIC_setLinkCheckMode(0);
            break;
        case EV_RFU1:
            Serial.println(F("EV_RFU1"));
            break;
        case EV_JOIN_FAILED:
            Serial.println(F("EV_JOIN_FAILED"));
            break;
        case EV_REJOIN_FAILED:
            Serial.println(F("EV_REJOIN_FAILED"));
            break;
            break;
        case EV_TXCOMPLETE:
            Serial.println(F("EV_TXCOMPLETE (includes waiting for RX windows)"));
            if (LMIC.txrxFlags & TXRX_ACK)
              Serial.println(F("Received ack"));
            if (LMIC.dataLen) {
              Serial.println(F("Received "));
              Serial.println(LMIC.dataLen);
              Serial.println(F(" bytes of payload"));
            }
            // Schedule next transmission
            os_setTimedCallback(&sendjob, os_getTime()+sec2osticks(TX_INTERVAL), do_send);
            break;
        case EV_LOST_TSYNC:
            Serial.println(F("EV_LOST_TSYNC"));
            break;
        case EV_RESET:
            Serial.println(F("EV_RESET"));
            break;
        case EV_RXCOMPLETE:
            // data received in ping slot
            Serial.println(F("EV_RXCOMPLETE"));
            break;
        case EV_LINK_DEAD:
            Serial.println(F("EV_LINK_DEAD"));
            break;
        case EV_LINK_ALIVE:
            Serial.println(F("EV_LINK_ALIVE"));
            break;
         default:
            Serial.println(F("Unknown event"));
            break;
    }
}

void do_send(osjob_t* j){
    // Check if there is not a current TX/RX job running
    if (LMIC.opmode & OP_TXRXPEND) {
        Serial.println(F("OP_TXRXPEND, not sending"));
    } else {
        // grab latest GPS data for 2 seconds
        Serial.println(F("GPS data received:"));
        unsigned long start = millis();
        do {
          while (SoftSerial.available()) {
            char c = SoftSerial.read();
            gps.encode(c);
            Serial.write(c);
          }
        } while (millis() - start < 2000);

        // grab latitude, longitude, altitude
        float f_alt;
        long i_lat, i_lon, i_alt;
        // grab time from GPS
        unsigned long gps_date, gps_time;
        // age of GPS fix, milliseconds (should be <1000)
        unsigned long p_age, t_age; 
        
        gps.get_position(&i_lat, &i_lon, &p_age);
        gps.get_datetime(&gps_date, &gps_time, &t_age);

        f_alt = gps.f_altitude();  //get altitude
        i_alt = (long) f_alt * 100; // cast to int

        byte xmit[] = "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0";
        
        Serial.println();
        
        Serial.print("Latitude: ");
        Serial.println(i_lat);


        xmit[0] = (i_lat & 0xFF000000) >> 24;
        xmit[1] = (i_lat & 0x00FF0000) >> 16;
        xmit[2] = (i_lat & 0x0000FF00) >>  8;
        xmit[3] = (i_lat & 0x000000FF);

        Serial.print("Longitude: ");
        Serial.println(i_lon);
        xmit[4] = (i_lon & 0xFF000000) >> 24;
        xmit[5] = (i_lon & 0x00FF0000) >> 16;
        xmit[6] = (i_lon & 0x0000FF00) >>  8;
        xmit[7] = (i_lon & 0x000000FF);
        
        Serial.print("Altitude: ");
        Serial.println(i_alt);
        xmit[8]  = (i_alt & 0xFF000000) >> 24;
        xmit[9]  = (i_alt & 0x00FF0000) >> 16;
        xmit[10] = (i_alt & 0x0000FF00) >>  8;
        xmit[11] = (i_alt & 0x000000FF);
        
        Serial.print("Date: ");
        Serial.println(gps_date);
        xmit[12] = (gps_date & 0xFF000000) >> 24;
        xmit[13] = (gps_date & 0x00FF0000) >> 16;
        xmit[14] = (gps_date & 0x0000FF00) >>  8;
        xmit[15] = (gps_date & 0x000000FF);
        
        Serial.print("Time: ");
        Serial.println(gps_time);
        xmit[16] = (gps_time & 0xFF000000) >> 24;
        xmit[17] = (gps_time & 0x00FF0000) >> 16;
        xmit[18] = (gps_time & 0x0000FF00) >>  8;
        xmit[19] = (gps_time & 0x000000FF);
        
        Serial.print("Timestamp Age: ");
        Serial.println(p_age);
        Serial.println();

        // Prepare upstream data transmission at the next possible time.
        LMIC_setTxData2(1, xmit, sizeof(xmit)-1, 0);
        Serial.println(F("Packet queued"));
    }
    // Next TX is scheduled after TX_COMPLETE event.
}

void setup() {
    Serial.begin(9600);
    Serial.println(F("Starting"));

    SoftSerial.begin(9600); // open software serial

    #ifdef VCC_ENABLE
    // For Pinoccio Scout boards
    pinMode(VCC_ENABLE, OUTPUT);
    digitalWrite(VCC_ENABLE, HIGH);
    delay(1000);
    #endif

    // LMIC init
    os_init();
    Serial.println(F("os_init() done"));
    // Reset the MAC state. Session and pending data transfers will be discarded.
    LMIC_reset();
    Serial.println(F("LMIC_reset() done"));

    // THIS IS WHERE THE AUSTRALIA FREQUENCY MAGIC HAPPENS!
    // The frequency plan is hard-coded
    // But the band (or selected 8 channels) is configured here!
    // This is the same AU915 band as used by TTN
    
    // First, disable channels 0-7
    for (int channel=0; channel<8; ++channel) {
      LMIC_disableChannel(channel);
    }
    Serial.println(F("LMIC_disableChannel(0-7) done"));
    // Now, disable channels 16-72 (is there 72 ??)
    for (int channel=16; channel<72; ++channel) {
       LMIC_disableChannel(channel);
    }
    Serial.println(F("LMIC_disableChannel(16-72) done"));
    // This means only channels 8-15 are up

    // Disable link check validation
    //LMIC_setLinkCheckMode(0);
    
    // Start job (sending automatically starts OTAA too)
    do_send(&sendjob);
}

void loop() {
    os_runloop_once();
}
