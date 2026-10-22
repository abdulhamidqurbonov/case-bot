"""Katalogni bazadan yuklash: kodda yozilgan case/skinlar + bot orqali qo'shilganlar."""
import logging

from app import catalog, media
from app import database as dbm

logger = logging.getLogger(__name__)


def reload() -> None:
    skins, cases, hidden = dbm.catalog_rows()
    catalog.apply(skins, cases, hidden)
    media.refresh_keys()
    logger.info("Katalog: %d skin, %d case (bot orqali: %d skin, %d case, yashirin: %d)",
                len(catalog.SKINS), len(catalog.CASE_LIST), len(skins), len(cases), len(hidden))
