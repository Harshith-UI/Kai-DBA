import os
import logging
import oracledb
from dotenv import load_dotenv

load_dotenv()
logger=logging.getLogger(__name__)
ORACLE_USER = os.getenv("ORACLE_USER")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD")
WALLET_DIR = os.path.join(os.path.dirname(__file__), "wallet")


def get_connection():
    logger.info("Connecting to Oracle DB")
    logger.debug("Using wallet directory: %s", WALLET_DIR)
    connection = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn="peo953mw0xpu8eho_medium",
        config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.getenv("WALLET_PASSWORD")
    )
    logger.info("Oracle DB connection established")
    return connection


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s"
    )
    try:
        conn = get_connection()
        logger.info("Connected to Oracle DB successfully")
        logger.info("Database version: %s", conn.version)
        conn.close()
    except oracledb.Error as e:
        logger.error("Error connecting to Oracle DB: %s", e)
