// ===================================================================================
// Project:   TapeMate64 - Connect your Commodore Datasette to a PC
// Version:   v1.0
// Year:      2025
// Author:    Yannick Heneault (Based on work of Stefan Wagner)
// Github:    https://github.com/heneault/TapeMate64
// License:   http://creativecommons.org/licenses/by-sa/3.0/
// ===================================================================================
//
// Description:
// ------------
// TapeMate64 is a simple and inexpensive adapter that allows a Commodore Datasette
// to interface with your computer via USB for reading from or writing to tapes.
// This project is based on TapeBuddy64 but uses off-the-shelf modular components
// and fixes a few limitations.
//  
// It uses the Arduino Nano Supermini module, which includes the ATmega328P processor.
// It also uses the MT3608 module to boost voltage for the motor, along with some
// discrete components.
//  
// A custom PCB is not required, although one may be available.
// The assembly process is relatively quick and easy using a perforated board.
// Additionally, the cost of the required modules is very low.
//
// Operating Instructions:
// -----------------------
// - Connect your TapeMate64 to your Commodore Datasette.
// - Connect your TapeMate64 to a USB port of your PC.
// - Execute the desired Python script on your PC.
//
// The Python scripts control the device via four simple serial commands:
//
// Command    Function                            Response
// "i"        transmit indentification string     "TapeMate64\n"
// "v"        transmit firmware version number    e.g. "v1.0\n"
// "r"        read file from tape                 send raw data stream
// "w"        write file to tape                  receive raw data stream

// ===================================================================================
// Libraries, Definitions and Macros
// ===================================================================================

// Libraries
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <util/atomic.h>

// Pin definitions
#define PIN_LED   2 // pin connected to the Neopixel strip
#define PIN_READ  8 // pin connected to READ on datasette port (D8)
#define PIN_WRITE 7 // pin connected to WRITE on datasette port (D7)
#define PIN_SENSE 3 // pin connected to SENSE on datasette port (D3)
#define PIN_MOTOR 5 // pin connected to MOTOR control (D5)

// Configuration parameters
#define UART_BAUD     250000 // UART: baud rate
#define TAP_WAIT_PLAY 10     // TAPE: time in seconds to wait for PLAY pressed
#define TAP_TIMEOUT   15     // TAPE: time in seconds to wait for pulses
#define TAP_PACKSIZE  64     // length of data package for writing (max TAP_BUF_LEN / 2)
#define TAP_BUF_LEN   256    // tape buffer length (must be byte size)

// Identifiers
#define VERSION "1.0"        // version number sent via serial if requested
#define IDENT "TapeMate64"   // identifier sent via serial if requested

#define pinLow(x) (PORTD &= (~(1 << x)))
#define pinHigh(x) (PORTD |= (1 << x))
#define pinRead(x) (PIND & (1 << x))

// ===================================================================================
// UART Implementation (8N1, no buffer, no interrupts)
// ===================================================================================

#define UART_send(x) UDR0 = (x)
#define UART_ready() (UCSR0A & _BV(UDRE0))
#define UART_available() (UCSR0A & _BV(RXC0))

void UART_init(void)
{
  uint16_t baud_setting = (F_CPU / 4 / UART_BAUD - 1) / 2;
  UBRR0H = baud_setting >> 8;
  UBRR0L = baud_setting;
  UCSR0A = _BV(U2X0);
  UCSR0C = _BV(UCSZ01) | _BV(UCSZ00);
  UCSR0B = _BV(RXEN0) | _BV(TXEN0);
}

uint8_t UART_read(void)
{
  while (!UART_available());
  return UDR0;
}

void UART_write(uint8_t data)
{
  while (!UART_ready());
  UART_send(data);
}

void UART_print(const char *str)
{
  while (*str)
    UART_write(*str++);
}

void UART_println(const char *str)
{
  UART_print(str);
  UART_write('\n');
}

void UART_flushRX(void)
{
  do
  {
    UDR0;
    _delay_ms(1);
  } while (UART_available());
}

// ===================================================================================
// Leds implementation (on board leds)
// ===================================================================================

// Leds color index
#define RED_LED 0
#define GREEN_LED 1
#define BLUE_LED 2
#define NUM_LED 3

Adafruit_NeoPixel LED_controller;

void LED_turnOn(uint8_t color);

void LED_init()
{
  LED_controller = Adafruit_NeoPixel(NUM_LED, PIN_LED, NEO_GRB + NEO_KHZ800);
  LED_controller.begin();
  for (uint8_t i = 0; i < 3; i++)
  {
    LED_controller.setPixelColor(i, LED_controller.Color(0, 0, 0));
    LED_controller.setPixelColor(i, LED_controller.Color(0, 0, 0));
    LED_controller.setPixelColor(i, LED_controller.Color(0, 0, 0));
  }
  LED_turnOn(BLUE_LED);
  LED_controller.setBrightness(64);
  LED_controller.show();
}

void LED_turnOn(uint8_t color)
{
  uint32_t rgb = 0;
  switch (color)
  {
  case RED_LED:
    rgb = LED_controller.Color(255, 0, 0);
    break;
  case GREEN_LED:
    rgb = LED_controller.Color(0, 255, 0);
    break;
  case BLUE_LED:
    rgb = LED_controller.Color(0, 0, 255);
    break;
  }
  LED_controller.setPixelColor(1, rgb);
  LED_controller.show();
}

void LED_turnOff(uint8_t color)
{
  LED_controller.setPixelColor(1, LED_controller.Color(0, 0, 0));
  LED_controller.show();
}

void LED_toggle(uint8_t color)
{
  if (LED_controller.getPixelColor(1) == LED_controller.Color(0, 0, 0))
    LED_turnOn(color);
  else
    LED_turnOff(color);
}

// ===================================================================================
// Timeout Counter using arduino default timer (timer0)
// ===================================================================================

volatile uint8_t RTC_timeout_sec;
volatile unsigned long RTC_expiry_time;

void RTC_reset(void);

void RTC_init(void)
{
  RTC_timeout_sec = 0;
  RTC_expiry_time = 0xFFFFFFFF;
}

void RTC_start(uint8_t timeout)
{
  RTC_timeout_sec = timeout;
  RTC_reset();
}

void RTC_reset(void)
{
  RTC_expiry_time = millis() + RTC_timeout_sec * 1000;
}

bool RTC_isTimeout()
{
  return millis() > RTC_expiry_time;
}

// ===================================================================================
// Datasette Port Interface Implementation - Setup
// ===================================================================================

volatile uint8_t TAP_buf[TAP_BUF_LEN];
volatile uint8_t TAP_buf_ovf;
volatile uint8_t TAP_buf_unr;
volatile uint8_t TAP_buf_head;
volatile uint8_t TAP_buf_tail;
volatile bool TAP_signal_2nd_half;
volatile uint16_t TAP_pulse_timer;
volatile uint16_t TAP_pulse_over;
volatile uint16_t TAP_pulse_timer_save;
volatile uint16_t TAP_pulse_over_save;

#define TAP_available() (TAP_buf_head != TAP_buf_tail)

// Setup TAP interface
void TAP_init(void)
{
  // Setup Pins
  DDRD = _BV(PIN_WRITE) | _BV(PIN_MOTOR);
  PORTB = _BV(PIN_READ - 8);
  PORTD = _BV(PIN_SENSE);
}

// Get number of items in tape buffer
uint8_t TAP_buf_items(void)
{
  uint8_t head = TAP_buf_head;
  uint8_t tail = TAP_buf_tail;
  if (head > tail)
    return (head - tail);
  return (TAP_BUF_LEN - tail + head);
}

uint16_t TAP_crc16_update(uint16_t crc, uint8_t data)
{
  crc ^= data;
  for (int i = 0; i < 8; i++)
  {
    if (crc & 1)
      crc = (crc >> 1) ^ 0xA001;
    else
      crc >>= 1;
  }
  return crc;
}

// ===================================================================================
// Datasette Port Interface Implementation - Read from Tape
// ===================================================================================

// Read from Datasette
void TAP_read(void)
{
  // Wait until PLAY has been pressed on the tape or timeout occurs
  pinLow(PIN_MOTOR);
  LED_turnOff(BLUE_LED);
  RTC_start(TAP_WAIT_PLAY);
  while (pinRead(PIN_SENSE) && !RTC_isTimeout())
  {
    LED_toggle(GREEN_LED);
    _delay_ms(100);
  }

  if (RTC_isTimeout())
  {
    LED_turnOff(GREEN_LED);
    LED_turnOn(BLUE_LED);
    UART_write(1);
    return;
  }

  // Prepare reading from tape
  uint16_t checksum = 0xFFFF;
  TAP_buf_ovf = 0;
  TAP_buf_head = 0;
  TAP_buf_tail = 0;
  TAP_pulse_over = 0;
  TAP_pulse_timer = 0;
  uint8_t count = 0;

  UART_write(0); // send 'PLAY' to PC
  LED_turnOn(GREEN_LED);
  pinHigh(PIN_MOTOR);
  _delay_ms(100);
  RTC_start(TAP_TIMEOUT);

  TCCR1A = 0;
  TCCR1B = 0;
  TIFR1 = 0xFF;
  TCNT1 = 0;
  TIMSK1 = _BV(ICIE1) | _BV(TOIE1);
  TCCR1B = _BV(CS11) | _BV(ICNC1);

  // Read from tape
  while (1)
  {
    // Check finish conditions
    if (pinRead(PIN_SENSE))
      break;
    if (RTC_isTimeout())
      break;
    ATOMIC_BLOCK(ATOMIC_FORCEON)
    {
      if (TAP_buf_ovf)
        break;
    }

    // Check send data conditions
    if (UART_ready())
    {
      bool send = false;
      uint8_t data;
      ATOMIC_BLOCK(ATOMIC_FORCEON)
      {
        if (TAP_available())
        {
          data = TAP_buf[TAP_buf_tail++];
          send = true;
        }
      }
      if (send)
      {
        UART_send(data);
        checksum = TAP_crc16_update(checksum, data);
        count++;
        if (count == 3)
          count = 0;
        RTC_reset();
      }
    }
  }

  // Finish reading
  TCCR1B = 0;
  while (count && count % 3 != 0)
  {
    UART_write(1);
    checksum = TAP_crc16_update(checksum, 1);
    count++;
  }
  for (int i = 0; i < 3; i++)
  {
    // send 'STOP' to PC
    UART_write(0);
  }
  UART_write(checksum);
  UART_write(checksum >> 8);
  UART_write(TAP_buf_ovf);
  pinLow(PIN_MOTOR);
  while (!pinRead(PIN_SENSE))
  {
    LED_toggle(GREEN_LED);
    _delay_ms(100);
  }
  LED_turnOff(GREEN_LED);
  LED_turnOn(BLUE_LED);
}

// Timer capture interrupt service routine
ISR(TIMER1_CAPT_vect)
{
  TCNT1 = 0;
  TAP_pulse_timer = ICR1;

  if (TAP_pulse_timer < 17 && !TAP_pulse_over)
    return; // ignore very short pulse

  TAP_pulse_timer >>= 1;
  TAP_pulse_over >>= 1;

  TAP_buf[TAP_buf_head++] = TAP_pulse_timer & 0xFF;
  TAP_buf[TAP_buf_head++] = (TAP_pulse_timer >> 8) & 0xFF;
  TAP_buf[TAP_buf_head++] = TAP_pulse_over & 0xFF;

  if (!TAP_available())
    TAP_buf_ovf = 1;

  TAP_pulse_over = 0;
}

// Timer overflow interrupt service routine
ISR(TIMER1_OVF_vect)
{
  if (TAP_pulse_over < 0x1FF)
  {
    TAP_pulse_over++;
  }
}

// ===================================================================================
// Datasette Port Interface Implementation - Write to Tape
// ===================================================================================

// Write to Datasette
void TAP_write(void)
{
  uint8_t requested = 0;
  uint8_t endofdata = 0;
  uint16_t checksum = 0xFFFF;
  TAP_signal_2nd_half = true;
  TAP_pulse_timer = 0;
  TAP_pulse_timer_save = 0;

  LED_turnOff(BLUE_LED);
  pinLow(PIN_MOTOR);
  RTC_start(TAP_WAIT_PLAY);
  while (pinRead(PIN_SENSE) && !RTC_isTimeout())
  {
    LED_toggle(RED_LED);
    _delay_ms(100);
  }
  if (RTC_isTimeout())
  {
    UART_write(1);
    LED_turnOff(RED_LED);
    LED_turnOn(BLUE_LED);
    return;
  }

  // Fill tape buffer with first data package
  UART_write(0); // send 'READY' to PC
  const uint8_t initial_data_request = (TAP_BUF_LEN - 3) / 3;
  const uint8_t initial_byte_request = initial_data_request * 3;
  UART_write(initial_data_request);
  for (uint8_t i = 0; i < initial_byte_request; i++)
  {
    uint8_t data = UART_read();
    TAP_buf[i] = data;
    checksum = TAP_crc16_update(checksum, data);
  }
  TAP_buf_head = initial_byte_request;
  TAP_buf_tail = 0;
  TAP_buf_unr = 0;

  // Prepare writing to tape
  LED_turnOn(RED_LED);
  pinHigh(PIN_WRITE);
  pinHigh(PIN_MOTOR);
  _delay_ms(100);

  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1 = 0;
  OCR1A = 0xFFFF;
  TIFR1 = 0xFF;
  TIMSK1 = _BV(OCIE1A);
  TCCR1B = _BV(CS11) | _BV(WGM12);

  // Write to tape
  while (1)
  {
    if (pinRead(PIN_SENSE))
      break;
    ATOMIC_BLOCK(ATOMIC_FORCEON)
    {
      if (TAP_buf_unr)
        break;
    }
    if (!TCCR1B)
      break;
    if (UART_available())
    {
      uint8_t data1 = UART_read();
      uint8_t data2 = UART_read();
      uint8_t data3 = UART_read();

      ATOMIC_BLOCK(ATOMIC_FORCEON)
      {
        TAP_buf[TAP_buf_head++] = data1;
        TAP_buf[TAP_buf_head++] = data2;
        TAP_buf[TAP_buf_head++] = data3;
      }
      if (requested)
        requested -= 1;

      if (!(data1 | data2 | data3))
      {
        endofdata = 1;
      }
      else
      {
        checksum = TAP_crc16_update(checksum, data1);
        checksum = TAP_crc16_update(checksum, data2);
        checksum = TAP_crc16_update(checksum, data3);
      }
    }

    if (!requested && !endofdata)
    {
      uint8_t r;
      ATOMIC_BLOCK(ATOMIC_FORCEON)
      {
        r = TAP_buf_items();
      }
      if ((TAP_BUF_LEN - r) > TAP_PACKSIZE)
      {
        requested = (TAP_BUF_LEN - r - 3) / 3;
        UART_write(requested);
      }
    }
  }

  // Finish writing
  TCCR1B = 0;
  TIMSK1 = 0;
  TIFR1 = 0xFF;
  UART_write(0);
  UART_write(checksum);
  UART_write(checksum >> 8);
  UART_write(TAP_buf_unr);
  UART_write(pinRead(PIN_SENSE));
  _delay_ms(500);
  pinLow(PIN_MOTOR);
  while (!pinRead(PIN_SENSE))
  {
    LED_toggle(RED_LED);
    _delay_ms(100);
  }
  LED_turnOff(RED_LED);
  LED_turnOn(BLUE_LED);
  UART_flushRX();
}

// Timer compare interrupt service routine
ISR(TIMER1_COMPA_vect)
{
  if (TAP_signal_2nd_half)
    pinHigh(PIN_WRITE);
  else
    pinLow(PIN_WRITE);

  if (!TAP_pulse_timer && !TAP_pulse_over)
  {
    if (TAP_pulse_timer_save || TAP_pulse_over_save)
    {
      TAP_pulse_timer = TAP_pulse_timer_save;
      TAP_pulse_over = TAP_pulse_over_save;
      TAP_pulse_timer_save = 0;
      TAP_pulse_over_save = 0;
    }
    else
    {
      if (!TAP_available())
      {
        TAP_buf_unr = 1;
        TCCR1B = 0;
        return;
      }

      uint8_t data1 = TAP_buf[TAP_buf_tail++];
      uint8_t data2 = TAP_buf[TAP_buf_tail++];
      uint8_t data3 = TAP_buf[TAP_buf_tail++];
      TAP_pulse_timer = (data2 << 8) | data1;
      TAP_pulse_over = data3;

      int32_t pulse_length = (int32_t(TAP_pulse_over)) << 16 | TAP_pulse_timer;
      if (!pulse_length)
      {
        TCCR1B = 0;
        return;
      }

      if (pulse_length > 1000)
      {
        // for long pulse, create a very short pulse first to go to high level
        // otherwise the long delay in rise sometime glitch the datassette to write a false extra pulse
        pulse_length = pulse_length * 2;
        TAP_pulse_timer = 50;
        TAP_pulse_over = 0;
        pulse_length -= TAP_pulse_timer;
        TAP_pulse_timer_save = pulse_length & 0xffff;
        TAP_pulse_over_save = (pulse_length >> 16) & 0xffff;
      }
      else
      {
        TAP_pulse_timer_save = TAP_pulse_timer;
        TAP_pulse_over_save = TAP_pulse_over;
      }
    }
  }

  if (TAP_pulse_over)
  {
    if (TAP_pulse_over == 1 && TAP_pulse_timer < 1000) // split the final pulse to avoid OCR1A close to 0
    {
      uint16_t half_pulse = (1 << 15) | (TAP_pulse_timer >> 1);
      TAP_pulse_timer = half_pulse;
      OCR1A = half_pulse;
    }
    else
    {
      OCR1A = 0xFFFF;
    }
    TAP_pulse_over--;
  }
  else
  {
    OCR1A = TAP_pulse_timer;
    TAP_pulse_timer = 0;
    TAP_signal_2nd_half = !TAP_signal_2nd_half;
  }
}

// ===================================================================================
// Main Function
// ===================================================================================
void setup()
{
  UART_init();
  RTC_init();
  TAP_init();
  LED_init();
  interrupts();
}

void loop()
{
  if (pinRead(PIN_SENSE))
    pinLow(PIN_MOTOR);
  else
    pinHigh(PIN_MOTOR);

  if (UART_available())
  {
    uint8_t cmd = UART_read();
    switch (cmd)
    {
    case 'i':
      UART_println(IDENT);
      break;
    case 'v':
      UART_println(VERSION);
      break;
    case 'r':
      TAP_read();
      break;
    case 'w':
      TAP_write();
      break;
    default:
      break;
    }
  }
}
