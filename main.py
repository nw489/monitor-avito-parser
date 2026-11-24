# main.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio
import json
from typing import Optional, List
import uvicorn
from datetime import datetime

from parser_avito import parse_avito
from parser_yula import parse_yula
from parser_barahla import parse_barahla
from database import save_ads, get_all_ads, delete_old_ads

app = FastAPI(title="Avito Monitor API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_connections: list[WebSocket] = []
monitoring_tasks: dict[str, asyncio.Task] = {}


class SearchRequest(BaseModel):
    query: str
    price_from: Optional[int] = None
    price_to: Optional[int] = None
    max_price: Optional[int] = None
    city: Optional[str] = "Все регионы"
    sources: Optional[List[str]] = ["avito"]


@app.get("/")
async def root():
    return FileResponse("avito-monitor.html")


@app.post("/search")
async def search_ads(request: SearchRequest):
    try:
        print(f"🔍 Поиск: {request.query}, цена: {request.price_from}-{request.price_to}, город: {request.city}, источники: {request.sources}")

        limit_price = request.price_to if request.price_to is not None else request.max_price
        all_ads = []

        # Парсим по выбранным источникам
        tasks = []
        if "avito" in request.sources:
            tasks.append(parse_avito(request.query, limit_price, city=request.city))
        if "youla" in request.sources:
            tasks.append(parse_yula(request.query, limit_price, city=request.city))
        if "barahla" in request.sources:
            tasks.append(parse_barahla(request.query, limit_price, city=request.city))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            source = request.sources[i] if i < len(request.sources) else "unknown"
            if isinstance(result, list):
                all_ads.extend(result)
                print(f"✅ {source}: {len(result)} объявлений")
            elif isinstance(result, Exception):
                print(f"❌ Ошибка {source}: {result}")

        # Фильтруем по цене "от"
        if request.price_from is not None:
            all_ads = [ad for ad in all_ads if ad['price'] >= request.price_from]
        if request.price_to is not None:
            all_ads = [ad for ad in all_ads if ad['price'] <= request.price_to]

        # Удаляем дубликаты по id + source
        seen = set()
        unique_ads = []
        for ad in all_ads:
            key = f"{ad['id']}_{ad.get('source', 'unknown')}"
            if key not in seen:
                seen.add(key)
                unique_ads.append(ad)
        all_ads = unique_ads

        # Сортируем по цене
        all_ads.sort(key=lambda x: x['price'])

        new_count = save_ads(
            all_ads,
            request.query,
            price_from=request.price_from,
            price_to=request.price_to,
            max_price=request.max_price,
            city=request.city
        )

        print(f"📊 Всего найдено: {len(all_ads)} (новых: {new_count})")

        return {
            "status": "success",
            "count": len(all_ads),
            "new_count": new_count,
            "ads": all_ads
        }
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ads")
async def get_ads(query: Optional[str] = None, city: Optional[str] = None):
    ads = get_all_ads(query, city)
    return {
        "status": "success",
        "count": len(ads),
        "ads": [
            {
                "id": ad.id,
                "title": ad.title,
                "price": ad.price,
                "url": ad.url,
                "location": ad.location,
                "city": ad.city,
                "source": ad.source,
                "description": ad.description,
                "image_url": ad.image_url,
                "found_at": ad.found_at.isoformat()
            }
            for ad in ads
        ]
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    
    # Отправляем подтверждение
    await websocket.send_json({
        "type": "connected",
        "message": "Подключено к монитору Avito"
    })
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "start_monitoring":
                    query = message.get("query")
                    max_price = message.get("max_price")
                    price_from = message.get("price_from")
                    price_to = message.get("price_to")
                    city = message.get("city", "Все регионы")
                    sources = message.get("sources", ["avito"])
                    
                    limit_price = price_to if price_to is not None else max_price
                    
                    # Уникальный ключ для задачи мониторинга
                    key = f"{query}:{price_from}:{price_to}:{city}:{','.join(sources)}"
                    
                    # Отменяем старую задачу если есть
                    if key in monitoring_tasks:
                        monitoring_tasks[key].cancel()
                        try:
                            await monitoring_tasks[key]
                        except asyncio.CancelledError:
                            pass
                        del monitoring_tasks[key]
                    
                    # Создаем новую задачу
                    task = asyncio.create_task(
                        monitor_all_sites(
                            websocket, query, price_from, price_to, 
                            limit_price, key, city, sources
                        )
                    )
                    monitoring_tasks[key] = task
                    print(f"🔄 Мониторинг запущен: {key}")

                elif msg_type == "stop_monitoring":
                    key = message.get("key")
                    if key and key in monitoring_tasks:
                        monitoring_tasks[key].cancel()
                        try:
                            await monitoring_tasks[key]
                        except asyncio.CancelledError:
                            pass
                        del monitoring_tasks[key]
                        print(f"⏹ Мониторинг остановлен: {key}")
                        await websocket.send_json({
                            "type": "monitoring_stopped",
                            "key": key
                        })

            except json.JSONDecodeError as e:
                print(f"⚠️ Ошибка парсинга JSON: {e}")
            except Exception as e:
                print(f"⚠️ Ошибка обработки сообщения: {e}")

    except WebSocketDisconnect:
        print("🔌 WebSocket отключён")
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)


async def monitor_all_sites(
    websocket: WebSocket, 
    query: str,
    price_from: Optional[int] = None,
    price_to: Optional[int] = None,
    max_price: Optional[int] = None,
    key: str = "",
    city: str = "Все регионы",
    sources: List[str] = ["avito"]
):
    seen_ids = set()
    first_run = True
    
    try:
        while True:
            try:
                print(f"🔄 Мониторинг: {query} (цена: {price_from}-{price_to}, город: {city}, источники: {sources})")
                
                all_ads = []
                tasks = []
                
                if "avito" in sources:
                    tasks.append(parse_avito(query, max_price, limit=10, city=city))
                if "youla" in sources:
                    tasks.append(parse_yula(query, max_price, limit=10, city=city))
                if "barahla" in sources:
                    tasks.append(parse_barahla(query, max_price, limit=10, city=city))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    source = sources[i] if i < len(sources) else "unknown"
                    if isinstance(result, list):
                        all_ads.extend(result)
                        print(f"✅ {source}: {len(result)} объявлений")
                    elif isinstance(result, Exception):
                        print(f"❌ Ошибка {source}: {result}")

                # Фильтруем по цене
                if price_from is not None:
                    all_ads = [ad for ad in all_ads if ad['price'] >= price_from]
                if price_to is not None:
                    all_ads = [ad for ad in all_ads if ad['price'] <= price_to]

                # Удаляем дубликаты
                seen = set()
                unique_ads = []
                for ad in all_ads:
                    ad_key = f"{ad['id']}_{ad.get('source', 'unknown')}"
                    if ad_key not in seen:
                        seen.add(ad_key)
                        unique_ads.append(ad)
                all_ads = unique_ads

                if all_ads:
                    save_ads(all_ads, query, price_from=price_from, price_to=price_to, max_price=max_price, city=city)

                # Определяем новые объявления
                new_ads = []
                for ad in all_ads:
                    ad_key = f"{ad['id']}_{ad.get('source', 'unknown')}"
                    if ad_key not in seen_ids:
                        new_ads.append(ad)
                        seen_ids.add(ad_key)

                if first_run and all_ads:
                    await websocket.send_json({
                        "type": "new_ads",
                        "count": len(all_ads),
                        "ads": all_ads,
                        "key": key,
                        "initial": True
                    })
                    first_run = False
                    print(f"📊 Первая загрузка: {len(all_ads)} объявлений")
                elif new_ads:
                    await websocket.send_json({
                        "type": "new_ads",
                        "count": len(new_ads),
                        "ads": new_ads,
                        "key": key
                    })
                    print(f"🆕 Новых объявлений: {len(new_ads)}")
                else:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "message": "Новых объявлений нет",
                        "checked_at": datetime.utcnow().isoformat()
                    })

                # Ждём 15 минут перед следующим запросом
                await asyncio.sleep(900)
                
            except asyncio.CancelledError:
                print(f"⏹ Мониторинг отменён: {key}")
                break
            except Exception as e:
                print(f"❌ Ошибка мониторинга: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
                await asyncio.sleep(60)
                
    except asyncio.CancelledError:
        print(f"⏹ Мониторинг отменён (внешний): {key}")
    finally:
        if key in monitoring_tasks:
            del monitoring_tasks[key]


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_ads())


async def cleanup_old_ads():
    while True:
        try:
            delete_old_ads(days=7)
            print("🧹 Очистка старых объявлений выполнена")
        except Exception as e:
            print(f"❌ Ошибка очистки: {e}")
        await asyncio.sleep(86400)  # Раз в день


@app.on_event("shutdown")
async def shutdown_event():
    for task in monitoring_tasks.values():
        task.cancel()
    print("👋 Сервер остановлен")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)