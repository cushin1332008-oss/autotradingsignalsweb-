import logging

from logging.handlers import RotatingFileHandler

logger=logging.getLogger("CuShinBot")

logger.setLevel(logging.INFO)

formatter=logging.Formatter(

"%(asctime)s | %(levelname)s | %(message)s"

)

file_handler=RotatingFileHandler(

"bot.log",

maxBytes=5*1024*1024,

backupCount=5

)

file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

console=logging.StreamHandler()

console.setFormatter(formatter)

logger.addHandler(console)
