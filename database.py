# database.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
from models import Ad, SearchHistory, Base

engine = create_engine('sqlite:///avito.db', connect_args={'check_same_thread': False})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def save_ads(ads_list, search_query, price_from=None, price_to=None, max_price=None, city=None):
    session = Session()
    new_count = 0
    try:
        for ad_data in ads_list:
            # Проверяем существование по ID + источнику
            existing = session.query(Ad).filter(
                Ad.id == ad_data['id'],
                Ad.source == ad_data.get('source', 'avito')
            ).first()
            if not existing:
                ad = Ad(
                    id=ad_data['id'],
                    title=ad_data['title'],
                    price=ad_data['price'],
                    url=ad_data.get('url') or '',
                    description=ad_data.get('description', ''),
                    location=ad_data.get('location', ''),
                    city=city,
                    search_query=search_query,
                    image_url=ad_data.get('image_url', ''),
                    source=ad_data.get('source', 'avito'),
                    found_at=datetime.utcnow()
                )
                session.add(ad)
                new_count += 1

        history = SearchHistory(
            query=search_query,
            price_from=price_from,
            price_to=price_to,
            max_price=max_price,
            city=city,
            results_count=len(ads_list)
        )
        session.add(history)
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
    return new_count


def get_new_ads(search_query, since_minutes=5):
    session = Session()
    cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
    ads = session.query(Ad).filter(
        Ad.search_query == search_query,
        Ad.found_at >= cutoff
    ).order_by(Ad.found_at.desc()).all()
    session.close()
    return ads


def get_all_ads(search_query=None, city=None):
    session = Session()
    query = session.query(Ad)
    if search_query:
        query = query.filter(Ad.search_query == search_query)
    if city:
        query = query.filter(Ad.city == city)
    ads = query.order_by(Ad.found_at.desc()).all()
    session.close()
    return ads


def delete_old_ads(days=7):
    session = Session()
    cutoff = datetime.utcnow() - timedelta(days=days)
    try:
        session.query(Ad).filter(Ad.found_at < cutoff).delete()
        session.commit()
    finally:
        session.close()