# models.py

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Ad(Base):
    __tablename__ = 'ads'

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    url = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String, nullable=True)
    city = Column(String, nullable=True)
    source = Column(String, nullable=True, default='avito')
    created_at = Column(DateTime, default=datetime.utcnow)
    found_at = Column(DateTime, default=datetime.utcnow)
    search_query = Column(String, nullable=False)
    image_url = Column(String, nullable=True)


class SearchHistory(Base):
    __tablename__ = 'search_history'

    id = Column(Integer, primary_key=True)
    query = Column(String, nullable=False)
    price_from = Column(Integer, nullable=True)
    price_to = Column(Integer, nullable=True)
    max_price = Column(Integer, nullable=True)
    city = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    results_count = Column(Integer, default=0)