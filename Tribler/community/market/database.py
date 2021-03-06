"""
This file contains everything related to persistence for the market community.
"""
from os import path


from Tribler.community.market.core.message import TraderId
from Tribler.community.market.core.order import Order, OrderId, OrderNumber
from Tribler.community.market.core.payment import Payment
from Tribler.community.market.core.quantity import Quantity
from Tribler.community.market.core.tick import Tick
from Tribler.community.market.core.transaction import Transaction, TransactionId, TransactionNumber
from Tribler.pyipv8.ipv8.attestation.trustchain.database import TrustChainDB

DATABASE_DIRECTORY = path.join(u"sqlite")
# Path to the database location + dispersy._workingdirectory
DATABASE_PATH = path.join(DATABASE_DIRECTORY, u"market.db")
# Version to keep track if the db schema needs to be updated.
LATEST_DB_VERSION = 2
# Schema for the Market DB.
schema = u"""
CREATE TABLE IF NOT EXISTS blocks(
 tx                   TEXT NOT NULL,
 public_key           TEXT NOT NULL,
 sequence_number      INTEGER NOT NULL,
 link_public_key      TEXT NOT NULL,
 link_sequence_number INTEGER NOT NULL,
 previous_hash	      TEXT NOT NULL,
 signature		      TEXT NOT NULL,

 insert_time          TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
 block_hash	          TEXT NOT NULL,

 PRIMARY KEY (public_key, sequence_number)
 );

CREATE TABLE IF NOT EXISTS orders(
 trader_id            TEXT NOT NULL,
 order_number         INTEGER NOT NULL,
 price                DOUBLE NOT NULL,
 price_type           TEXT NOT NULL,
 quantity             DOUBLE NOT NULL,
 quantity_type        TEXT NOT NULL,
 traded_quantity      DOUBLE NOT NULL,
 timeout              DOUBLE NOT NULL,
 order_timestamp      TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
 completed_timestamp  TIMESTAMP,
 is_ask               INTEGER NOT NULL,
 cancelled            INTEGER NOT NULL,
 verified             INTEGER NOT NULL,

 PRIMARY KEY (trader_id, order_number)
 );

 CREATE TABLE IF NOT EXISTS transactions(
  trader_id                TEXT NOT NULL,
  transaction_number       INTEGER NOT NULL,
  order_trader_id          TEXT NOT NULL,
  order_number             INTEGER NOT NULL,
  partner_trader_id        TEXT NOT NULL,
  partner_order_number     INTEGER NOT NULL,
  price                    DOUBLE NOT NULL,
  price_type               TEXT NOT NULL,
  transferred_price        DOUBLE NOT NULL,
  quantity                 DOUBLE NOT NULL,
  quantity_type            TEXT NOT NULL,
  transferred_quantity     DOUBLE NOT NULL,
  transaction_timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
  sent_wallet_info         INTEGER NOT NULL,
  received_wallet_info     INTEGER NOT NULL,
  incoming_address         TEXT NOT NULL,
  outgoing_address         TEXT NOT NULL,
  partner_incoming_address TEXT NOT NULL,
  partner_outgoing_address TEXT NOT NULL,
  match_id                 TEXT NOT NULL,

  PRIMARY KEY (trader_id, transaction_number)
 );

 CREATE TABLE IF NOT EXISTS payments(
  trader_id                TEXT NOT NULL,
  message_number           TEXT NOT NULL,
  transaction_trader_id    TEXT NOT NULL,
  transaction_number       INTEGER NOT NULL,
  payment_id               TEXT NOT NULL,
  transferee_quantity      DOUBLE NOT NULL,
  quantity_type            TEXT NOT NULL,
  transferee_price         DOUBLE NOT NULL,
  price_type               TEXT NOT NULL,
  address_from             TEXT NOT NULL,
  address_to               TEXT NOT NULL,
  timestamp                TIMESTAMP NOT NULL,
  success                  INTEGER NOT NULL,

  PRIMARY KEY (trader_id, message_number, transaction_trader_id, transaction_number)
 );

 CREATE TABLE IF NOT EXISTS ticks(
  trader_id            TEXT NOT NULL,
  order_number         INTEGER NOT NULL,
  price                DOUBLE NOT NULL,
  price_type           TEXT NOT NULL,
  quantity             DOUBLE NOT NULL,
  quantity_type        TEXT NOT NULL,
  timeout              DOUBLE NOT NULL,
  timestamp            TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
  is_ask               INTEGER NOT NULL,
  block_hash           TEXT NOT NULL,

  PRIMARY KEY (trader_id, order_number)
 );

 CREATE TABLE IF NOT EXISTS orders_reserved_ticks(
  trader_id              TEXT NOT NULL,
  order_number           INTEGER NOT NULL,
  reserved_trader_id     TEXT NOT NULL,
  reserved_order_number  INTEGER NOT NULL,
  quantity               DOUBLE NOT NULL,
  quantity_type          TEXT NOT NULL,

  PRIMARY KEY (trader_id, order_number, reserved_trader_id, reserved_order_number)
 );

 CREATE TABLE IF NOT EXISTS traders(
  trader_id            TEXT NOT NULL,
  ip_address           TEXT NOT NULL,
  port                 INTEGER NOT NULL,

  PRIMARY KEY(trader_id)
 );

CREATE TABLE option(key TEXT PRIMARY KEY, value BLOB);
INSERT INTO option(key, value) VALUES('database_version', '""" + str(LATEST_DB_VERSION) + u"""');
"""


class MarketDB(TrustChainDB):
    """
    Persistence layer for the Market Community.
    Connection layer to SQLiteDB.
    Ensures a proper DB schema on startup.
    """

    def get_schema(self):
        """
        Return the schema for the database.
        """
        return schema

    def get_all_blocks(self):
        """
        Return all blocks in the database.
        """
        return self._getall(u"", ())

    def get_block_with_hash(self, hash):
        """
        Return the block with a specific hash or None if it's not available in the database.
        """
        return self._get(u"WHERE block_hash = ?", (buffer(hash),))

    def get_all_orders(self):
        """
        Return all orders in the database.
        """
        db_result = self.execute(u"SELECT * FROM orders")
        return [Order.from_database(db_item, self.get_reserved_ticks(
            OrderId(TraderId(str(db_item[0])), OrderNumber(db_item[1])))) for db_item in db_result]

    def get_order(self, order_id):
        """
        Return an order with a specific id.
        """
        try:
            db_result = self.execute(u"SELECT * FROM orders WHERE trader_id = ? AND order_number = ?",
                                     (unicode(order_id.trader_id), unicode(order_id.order_number))).next()
        except StopIteration:
            return None
        return Order.from_database(db_result, self.get_reserved_ticks(order_id))

    def add_order(self, order):
        """
        Add a specific order to the database
        """
        self.execute(
            u"INSERT INTO orders (trader_id, order_number, price, price_type, quantity, quantity_type,"
            u"traded_quantity, timeout, order_timestamp, completed_timestamp, is_ask, cancelled, verified) "
            u"VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            order.to_database())
        self.commit()

        # Add reserved ticks
        for reserved_order_id, quantity in order.reserved_ticks.iteritems():
            self.add_reserved_tick(order.order_id, reserved_order_id, quantity)

    def delete_order(self, order_id):
        """
        Delete a specific order from the database
        """
        self.execute(u"DELETE FROM orders WHERE trader_id = ? AND order_number = ?",
                     (unicode(order_id.trader_id), unicode(order_id.order_number)))
        self.delete_reserved_ticks(order_id)

    def get_next_order_number(self):
        """
        Return the next order number from the database
        """
        highest_order_number = self.execute(u"SELECT MAX(order_number) FROM orders").next()
        if not highest_order_number[0]:
            return 1
        return highest_order_number[0] + 1

    def delete_reserved_ticks(self, order_id):
        """
        Delete all reserved ticks from a specific order
        """
        self.execute(u"DELETE FROM orders_reserved_ticks WHERE trader_id = ? AND order_number = ?",
                     (unicode(order_id.trader_id), unicode(order_id.order_number)))

    def add_reserved_tick(self, order_id, reserved_order_id, quantity):
        """
        Add a reserved tick to the database
        """
        self.execute(
            u"INSERT INTO orders_reserved_ticks (trader_id, order_number, reserved_trader_id, reserved_order_number,"
            u"quantity, quantity_type) VALUES(?,?,?,?,?,?)",
            (unicode(order_id.trader_id), unicode(order_id.order_number),
             unicode(reserved_order_id.trader_id), unicode(reserved_order_id.order_number),
             float(quantity), unicode(quantity.wallet_id)))
        self.commit()

    def get_reserved_ticks(self, order_id):
        """
        Get all reserved ticks for a specific order.
        """
        db_results = self.execute(u"SELECT * FROM orders_reserved_ticks WHERE trader_id = ? AND order_number = ?",
                                  (unicode(order_id.trader_id), unicode(order_id.order_number)))
        return [(OrderId(TraderId(str(data[2])), OrderNumber(data[3])),
                 Quantity(data[4], str(data[5]))) for data in db_results]

    def get_all_transactions(self):
        """
        Return all transactions in the database.
        """
        db_result = self.execute(u"SELECT * FROM transactions")
        return [Transaction.from_database(db_item,
                                          self.get_payments(TransactionId(TraderId(str(db_item[0])),
                                                                          TransactionNumber(db_item[1]))))
                for db_item in db_result]

    def get_transaction(self, transaction_id):
        """
        Return a transaction with a specific id.
        """
        try:
            db_result = self.execute(u"SELECT * FROM transactions WHERE trader_id = ? AND transaction_number = ?",
                                     (unicode(transaction_id.trader_id),
                                      unicode(transaction_id.transaction_number))).next()
        except StopIteration:
            return None
        return Transaction.from_database(db_result, self.get_payments(transaction_id))

    def add_transaction(self, transaction):
        """
        Add a specific transaction to the database
        """
        self.execute(
            u"INSERT INTO transactions (trader_id, transaction_number, order_trader_id, order_number,"
            u"partner_trader_id, partner_order_number, price, price_type, transferred_price, quantity, quantity_type,"
            u"transferred_quantity, transaction_timestamp, sent_wallet_info, received_wallet_info,"
            u"incoming_address, outgoing_address, partner_incoming_address, partner_outgoing_address, match_id) "
            u"VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", transaction.to_database())
        self.commit()

        self.delete_payments(transaction.transaction_id)
        for payment in transaction.payments:
            self.add_payment(payment)

    def delete_transaction(self, transaction_id):
        """
        Delete a specific transaction from the database
        """
        self.execute(u"DELETE FROM transactions WHERE trader_id = ? AND transaction_number = ?",
                     (unicode(transaction_id.trader_id), unicode(transaction_id.transaction_number)))
        self.delete_payments(transaction_id)

    def get_next_transaction_number(self):
        """
        Return the next transaction number from the database
        """
        highest_transaction_number = self.execute(u"SELECT MAX(transaction_number) FROM transactions").next()
        if not highest_transaction_number[0]:
            return 1
        return highest_transaction_number[0] + 1

    def add_payment(self, payment):
        """
        Add a specific transaction to the database
        """
        self.execute(
            u"INSERT INTO payments (trader_id, message_number, transaction_trader_id, transaction_number, payment_id,"
            u"transferee_quantity, quantity_type, transferee_price, price_type, address_from, address_to, timestamp,"
            u"success) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", payment.to_database())
        self.commit()

    def get_payments(self, transaction_id):
        """
        Return all payment tied to a specific transaction.
        """
        db_result = self.execute(u"SELECT * FROM payments WHERE transaction_trader_id = ? AND transaction_number = ?"
                                 u"ORDER BY timestamp ASC",
                                 (unicode(transaction_id.trader_id),
                                  unicode(transaction_id.transaction_number)))
        return [Payment.from_database(db_item) for db_item in db_result]

    def delete_payments(self, transaction_id):
        """
        Delete all payments that are associated with a specific transaction
        """
        self.execute(u"DELETE FROM payments WHERE transaction_trader_id = ? AND transaction_number = ?",
                     (unicode(transaction_id.trader_id), unicode(transaction_id.transaction_number)))

    def add_tick(self, tick):
        """
        Add a specific tick to the database
        """
        self.execute(
            u"INSERT INTO ticks (trader_id, order_number, price, price_type, quantity,"
            u"quantity_type, timeout, timestamp, is_ask, block_hash) "
            u"VALUES(?,?,?,?,?,?,?,?,?,?)", tick.to_database())
        self.commit()

    def delete_all_ticks(self):
        """
        Remove all ticks from the database.
        """
        self.execute(u"DELETE FROM ticks")

    def get_ticks(self):
        """
        Get all ticks present in the database.
        """
        return [Tick.from_database(db_tick) for db_tick in self.execute(u"SELECT * FROM ticks")]

    def add_trader_identity(self, trader_id, ip, port):
        self.execute(u"INSERT OR REPLACE INTO traders VALUES(?,?,?)", (unicode(trader_id), unicode(ip), port))
        self.commit()

    def get_traders(self):
        return [res for res in self.execute(u"SELECT * FROM traders")]

    def open(self, initial_statements=True, prepare_visioning=True):
        return super(MarketDB, self).open(initial_statements, prepare_visioning)

    def get_upgrade_script(self, current_version):
        if current_version == 1:
            return u"ALTER TABLE orders ADD COLUMN verified INTEGER DEFAULT 1 NOT NULL;" \
                   u"UPDATE option SET value=\"2\" WHERE key = \"database_version\";" \
                   u"ALTER TABLE ticks ADD COLUMN block_hash TEXT DEFAULT %s NOT NULL;" % ('0' * 32)

    def check_database(self, database_version):
        """
        Ensure the proper schema is used by the database.
        :param database_version: Current version of the database.
        :return:
        """
        assert isinstance(database_version, unicode)
        assert database_version.isdigit()
        assert int(database_version) >= 0
        database_version = int(database_version)

        if database_version == 0:
            self.executescript(self.get_schema())
            self.commit()
            database_version = LATEST_DB_VERSION

        while database_version < LATEST_DB_VERSION:
            upgrade_script = self.get_upgrade_script(current_version=database_version)
            if upgrade_script:
                self.executescript(upgrade_script)
            database_version += 1

        return LATEST_DB_VERSION
