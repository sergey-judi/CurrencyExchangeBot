# Import necessary modules
import telebot
import sqlite3
import requests
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Import necessary secret constants
from config import TOKEN, HOST, DB_NAME

bot = telebot.TeleBot(TOKEN)


def get_exchange_rates(message_date):
    """
    Extracts exchange rates from database OR saves them after extracting from the server
    :param message_date: Timestamp of received message
    :return: Exchange rates dictionary^ key - currency, value - rate to USD
    """
    # Connect to the database
    with sqlite3.connect(DB_NAME) as connection:
        # Getting its cursor
        cursor = connection.cursor()
        try:
            # Getting last synced time
            cursor.execute("SELECT timestamp FROM LastSynced;")
            last_saved_timestamp = cursor.fetchone()[0]

            # If last save was more than 10 minutes ago, update database
            if (message_date - last_saved_timestamp) > 60*10:
                # Update last synced timestamp
                cursor.execute("DELETE FROM LastSynced;")
                cursor.execute("INSERT INTO LastSynced(timestamp) VALUES (?);", (message_date,))

                # Get rates for base currency USD
                response = requests.get(HOST + 'latest', params={'base': 'USD'})

                if response.status_code == 200:
                    # Get exchange rates if OK
                    exchange_rates = response.json()['rates']
                    # Truncate table
                    cursor.execute("DELETE FROM ExchangeRates;")
                    # Insert new values
                    for currency, rate in exchange_rates.items():
                        cursor.execute("""INSERT INTO ExchangeRates(currency, rate) VALUES (?, ?);""", (currency, rate))
                else:
                    raise requests.ConnectionError('Can not connect to the server')
            # If last save was less than 10 minutes ago
            else:
                # Select all existing exchange rates
                cursor.execute("""SELECT currency, rate FROM ExchangeRates;""")
                rows = cursor.fetchall()
                # Place them to dictionary
                exchange_rates = {row[0]: row[1] for row in rows}
        except Exception as e:
            print(e)

        return exchange_rates


@bot.message_handler(commands=['list', 'lst'])
def show_rate_list(message):
    """
    Sends information about every currency available
    :param message: Information about message
    :return: None
    """
    # Get rates from the database or from the server with the given message timestamp
    exchange_rates = get_exchange_rates(message.date)
    # Prepare response string
    rows = ['Available rates for USD as base currency:']
    rows += [f'{currency}: {round(rate, 2)}' for currency, rate in exchange_rates.items()]
    # Form a list for currencies
    rate_list = '\n'.join(rows)
    # send it to user
    bot.send_message(message.chat.id, rate_list)


@bot.message_handler(commands=['exchange'])
def exchange_currencies(message):
    """
    Sends the money amount in new currency for the given USD amount
    :param message: Information about message
    :return: None
    """
    # Connect to the database
    with sqlite3.connect(DB_NAME) as connection:
        # Getting its cursor
        cursor = connection.cursor()
        try:
            # Correct message has a pattern
            split_msg = message.text.split()
            usd_amount = split_msg[1]
            new_currency = split_msg[-1].upper()
            # Getting rid of "$" sign in the beginning of money amount, converting str to float
            usd_amount = float(usd_amount[1:]) if '$' in usd_amount else float(usd_amount)

            # Getting rate for the necessary currency
            cursor.execute("SELECT rate FROM ExchangeRates WHERE currency = ?;", (new_currency,))
            rate = cursor.fetchone()[0]

            # Send information to user
            bot.send_message(message.chat.id, f'{usd_amount} USD is {round(usd_amount*rate, 2)} {new_currency}')
        except IndexError:
            bot.send_message(message.chat.id, 'Incorrect input. Please, try again.')
        except ValueError:
            bot.send_message(message.chat.id, 'Incorrect USD amount. Please, try again.')
        except TypeError:
            bot.send_message(message.chat.id, 'Second currency is not existing. Please, try again.')
        except sqlite3.OperationalError or sqlite3.Error as e:
            print(e)


@bot.message_handler(commands=['history'])
def show_history_graph(message):
    """
    Sends rate graph chart for the specified currencies
    :param message: Information about message
    :return: None
    """
    try:
        # Correct message has a pattern
        split_msg = message.text.split()
        # Placing both currencies into a list
        currencies = split_msg[1].split('/')
        # Getting base currency
        base_currency = currencies[0]
        # Getting second currency
        second_currency = currencies[1]
        # Getting recent period for visualization
        period = int(split_msg[-2])

        # Getting right side of time interval
        current_date = datetime.today()
        # Getting left side of time interval
        previous_date = current_date - timedelta(days=period)
        # Query parameters preparation
        period_params = {
            'start_at': f'{previous_date.year}-{previous_date.month}-{previous_date.day}',
            'end_at': f'{current_date.year}-{current_date.month}-{current_date.day}',
            'base': base_currency,
            'symbols': second_currency
        }

        # Sending GET query to the server
        response = requests.get(HOST + 'history', params=period_params)

        # Process if OK
        if response.status_code == 200:
            rates = response.json()['rates']
            # Sort rates by date
            rates = dict(sorted(rates.items()))
            # Separate date from rates
            xs = rates.keys()
            # Rate is a value of a subdictionary for each key in date_rate dictionary
            ys = [rate for date_rate in rates.values() for currency, rate in date_rate.items()]

            # Plot gathered data
            fig = plt.figure()
            plt.plot(xs, ys, color='red')
            plt.scatter(xs, ys, color='red')
            plt.xticks(rotation=60)
            plt.xlabel('Date')
            plt.ylabel('Rate')
            plt.title(' '.join(split_msg[1:]))
            plt.grid()
            # Save a picture locally
            fig.savefig('plot.png', dpi=fig.dpi, bbox_inches='tight')
            # Send a picture to user
            bot.send_photo(message.chat.id, photo=open('plot.png', 'rb'))
        else:
            raise requests.ConnectionError('Can not connect to the server')
    except IndexError:
        bot.send_message(message.chat.id, 'Incorrect base and second currencies. Please, try again.')
    except requests.ConnectionError:
        bot.send_message(message.chat.id, 'No exchange rate is available for the selected currency.')
    except ValueError:
        bot.send_message(message.chat.id, 'Incorrect history period. Please, try again.')
    except Exception as e:
        print(e)


@bot.message_handler(commands=['help'])
def bot_help(message):
    """
    Sends helpful information to a user
    :param message: Information about message
    :return: None
    """
    bot.send_message(
        message.chat.id,
        'Available commands: \n'
        '/list or /lst - show available rates \n'
        '/exchange [$usd_amount | usd_amount USD] to [currency_that_the_usd_amount_converts_to] - '
        'convert USD amount to another currency \n'
        '/history [first_currency]/[second_currency] for [recent period length] days - '
        'graph chart which shows the exchange rate for specified currencies \n'
    )


def init_db():
    """
    Initializes databases
    :return: None
    """
    with sqlite3.connect(DB_NAME) as connection:
        cursor = connection.cursor()
        try:
            # Create table for currencies exchange rate
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ExchangeRates(
                id INTEGER PRIMARY KEY,
                currency TEXT UNIQUE NOT NULL,
                rate REAL NOT NULL
                );
                """)

            # Create table for synchronisation time storing
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS LastSynced(
                id INTEGER PRIMARY KEY, 
                timestamp DATETIME NOT NULL
                ); 
                """)

            # Seed LastSynced database
            cursor.execute("""SELECT timestamp FROM LastSynced""")
            timestamp = cursor.fetchall()
            if not timestamp:
                cursor.execute("""INSERT INTO LastSynced(timestamp) VALUES(0)""")
        except sqlite3.Error as e:
            print(e)


if __name__ == '__main__':
    init_db()
    bot.polling()
