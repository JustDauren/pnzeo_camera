# PNZEO Camera для Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Полностью локальная интеграция камер PNZEO W8 для Home Assistant. Без облака, без китайских серверов, полный контроль.

## Возможности

- **Live View** — RTSP стрим через WebRTC (нулевая задержка)
- **PTZ** — поворот, наклон, зум, 16 пресетов, режим патрулирования
- **ИК подсветка** — вкл/выкл из HA
- **Детекция движения** — вкл/выкл из HA
- **Запись на SD** — старт/стоп записи
- **Настройки изображения** — яркость, контраст (слайдеры)
- **Разрешение** — 640p / 720p / 1080p
- **Зеркало/Переворот** — нормальный, вертикальный, горизонтальный
- **LED индикатор** — вкл/выкл
- **Перезагрузка** — удалённо
- **Снимок** — захват кадра
- **Форматирование SD** — (скрыто по умолчанию)

## Установка

### HACS (рекомендуется)
1. Откройте HACS в Home Assistant
2. Нажмите "Пользовательские репозитории"
3. Добавьте `https://github.com/JustDauren/pnzeo_camera` как "Интеграция"
4. Установите "PNZEO Camera"
5. Перезагрузите Home Assistant

### Вручную
Скопируйте `custom_components/pnzeo_camera/` в каталог `config/custom_components/` вашего HA.

## Настройка

1. Настройки → Устройства и службы → Добавить интеграцию
2. Найдите "PNZEO Camera"
3. Выберите "Вручную" или "Автопоиск"
4. Введите IP камеры и данные для входа (по умолчанию: admin / 8888)

## Сервисы

| Сервис | Описание |
|--------|----------|
| `pnzeo_camera.ptz_control` | Поворот/наклон/зум (up, down, left, right, center, zoom_in, zoom_out) |
| `pnzeo_camera.goto_preset` | Перейти к сохранённой позиции (0-15) |
| `pnzeo_camera.set_preset` | Сохранить текущую позицию (0-15) |
| `pnzeo_camera.send_command` | Отправить PPPP команду (для продвинутых) |

## Безопасность

Интеграция работает **100% локально** через RTSP и PPPP LAN протокол. Никакие облачные серверы не используются.

**Рекомендуется:** Заблокируйте весь исходящий трафик с IP камеры на роутере, чтобы камера не подключалась к китайским P2P relay серверам.

## Совместимость

Протестировано:
- PNZEO W8 (Model W8, префикс MTC888)

Должно работать с любой камерой, использующей приложения MTCam HD, minicam или iWFCam (протокол PPPP, префикс MTC/CAM).

## Авторы

- Протокол на основе [devbis/pppp_camera](https://github.com/devbis/pppp_camera) и [devbis/aiopppp](https://github.com/devbis/aiopppp)
- Анализ PPPP: [Wladimir Palant](https://palant.info/2025/11/05/an-overview-of-the-pppp-protocol-for-iot-cameras/), [Paul Marrapese (DEF CON 28)](https://hacked.camera/)
