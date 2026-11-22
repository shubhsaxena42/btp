#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild erp.db from schema.sql with GI registry data + a simulated operating history.

    .venv/bin/python seed.py

Deterministic (seed 42).  GI registry rows come from data/uk_gi.json (real IP India data);
everything else (organisation, members, products, customers, transactions) is fictional.
"""
import importlib.util
import json
import math
import os
import random
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('ERP_DB') or os.path.join(ROOT, 'erp.db')
SCHEMA = os.path.join(ROOT, 'schema.sql')
GI_JSON = os.path.join(ROOT, 'data', 'uk_gi.json')
GI_JSON_PROV = os.path.join(ROOT, 'data', 'uk_gi.provisional.json')

SIM_START = date(2026, 6, 1)
SIM_END = date(2026, 11, 22)
ORG_STATE_CODE = '05'
CATS = ('Agricultural', 'Handicraft', 'Manufactured', 'Foodstuff', 'Natural')

rng = random.Random(42)
random.seed(42)


def iso(d):
    return d.isoformat() if d else None


def D(s):
    return date.fromisoformat(s)


def load_enrichment():
    spec = importlib.util.spec_from_file_location('gi_enrichment', os.path.join(ROOT, 'data', 'gi_enrichment.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E = load_enrichment()
norm = E.norm


def gstin(state, pan):
    base = state + pan + '1Z'
    chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    total = 0
    for i, c in enumerate(base):
        v = chars.index(c) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return base + chars[(36 - total % 36) % 36]


def phone():
    return str(rng.choice([9, 8, 7])) + ''.join(str(rng.randint(0, 9)) for _ in range(9))


def r2(x):
    return round(x + 1e-9, 2)


# ------------------------------------------------------------------ static master data

ORG = {
    'org_name': "Kosi Valley Producers' Cooperative",
    'org_name_hi': 'कोसी घाटी ग्रामीण उत्पादक सहकारी समिति',
    'org_address': 'Kosi Road, Hawalbagh Block, Almora, Uttarakhand 263636',
    'org_address_hi': 'कोसी मार्ग, हवालबाग ब्लॉक, अल्मोड़ा, उत्तराखंड 263636',
    'org_district': 'Almora',
    'org_state': 'Uttarakhand',
    'org_state_code': ORG_STATE_CODE,
    'org_gstin': gstin('05', 'AAAFK4827M'),
    'org_phone': '9412345678',
    'org_email': 'info@kosivalleycoop.in',
    'org_upi': 'kosivalleycoop@okicici',
    'org_bank': 'Kumaon Zila Sahkari Bank, Hawalbagh Branch, A/c 0412010055679, IFSC KZSB0000412',
    'portal_url': 'https://gi-authentication-portal.vercel.app',
    'portal_manufacturer_name': "Kosi Valley Producers' Cooperative",
}

# name, hi, gender, village, block, district, shg, skill, skill_hi, [(gi keyword, au_valid_upto|None)], joined, active
MEMBERS = [
    ('Kamla Devi', 'कमला देवी', 'F', 'Hawalbagh', 'Hawalbagh', 'Almora', 'Maa Nanda Mahila SHG',
     'Aipan artist', 'ऐपण कलाकार', [('aipan', None)], '2023-04-12', 1),
    ('Basanti Bisht', 'बसंती बिष्ट', 'F', 'Lamgara', 'Lamgara', 'Almora', 'Jai Devbhoomi SHG',
     'Aipan artist and ringal weaver', 'ऐपण कलाकार और रिंगाल शिल्पकार', [('aipan', None), ('ringal', None)], '2023-06-20', 1),
    ('Hema Joshi', 'हेमा जोशी', 'F', 'Almora Town', 'Almora', 'Almora', 'Nanda Devi Mahila Samooh',
     'Aipan artist', 'ऐपण कलाकार', [('aipan', None)], '2023-07-03', 1),
    ('Govind Ram Tamta', 'गोविंद राम टम्टा', 'M', 'Tamta Mohalla, Almora', 'Almora', 'Almora', 'Tamta Shilp Samooh',
     'Copper craftsman', 'ताँबे के शिल्पकार', [('tamta', None)], '2023-04-12', 1),
    ('Pushpa Tamta', 'पुष्पा टम्टा', 'F', 'Tamta Mohalla, Almora', 'Almora', 'Almora', 'Tamta Shilp Samooh',
     'Copper craftswoman', 'ताँबे की शिल्पकार', [('tamta', None)], '2023-09-01', 1),
    ('Mohan Lal Tamta', 'मोहन लाल टम्टा', 'M', 'Tamta Mohalla, Almora', 'Almora', 'Almora', 'Tamta Shilp Samooh',
     'Copper craftsman', 'ताँबे के शिल्पकार', [('tamta', '2026-10-31')], '2023-04-12', 1),
    ('Pooja Pant', 'पूजा पंत', 'F', 'Dhauladevi', 'Dhauladevi', 'Almora', 'Kosi Ghati Mahila SHG',
     'Aipan artist', 'ऐपण कलाकार', [('aipan', '2026-12-14')], '2024-02-15', 1),
    ('Lakshmi Kanyal', 'लक्ष्मी कन्याल', 'F', 'Berinag', 'Berinag', 'Pithoragarh', 'Himalaya Chai Mahila Samooh',
     'Tea grower and chilli processor', 'चाय उत्पादक और मिर्च प्रसंस्करणकर्ता',
     [('berinag', '2027-01-08'), ('lakhori', None)], '2024-03-10', 1),
    ('Deepa Mehra', 'दीपा मेहरा', 'F', 'Darkot', 'Munsiyari', 'Pithoragarh', 'Panchachuli Weavers SHG',
     'Handloom weaver (dann, thulma)', 'हथकरघा बुनकर (दन, थुलमा)', [('bhotia', None), ('thulma', None)], '2023-08-18', 1),
    ('Kundan Singh Bora', 'कुंदन सिंह बोरा', 'M', 'Darkot', 'Munsiyari', 'Pithoragarh', 'Johar Kisan Samooh',
     'Rajma farmer', 'राजमा किसान', [('rajma', None)], '2023-10-05', 1),
    ('Geeta Arya', 'गीता आर्या', 'F', 'Dhauladevi', 'Dhauladevi', 'Almora', 'Kosi Ghati Mahila SHG',
     'Chilli grower and ringal weaver', 'मिर्च उत्पादक और रिंगाल शिल्पकार', [('lakhori', None), ('ringal', None)], '2024-05-22', 1),
    ('Narendra Singh Pangtey', 'नरेंद्र सिंह पांगती', 'M', 'Berinag', 'Berinag', 'Pithoragarh', 'Himalaya Chai Mahila Samooh',
     'Tea grower', 'चाय उत्पादक', [('berinag', None)], '2024-03-10', 1),
    ('Savitri Martolia', 'सावित्री मर्तोलिया', 'F', 'Sarmoli', 'Munsiyari', 'Pithoragarh', 'Maati Sangathan SHG',
     'Weaver (dann, thulma)', 'बुनकर (दन, थुलमा)', [('bhotia', None), ('thulma', '2026-12-29')], '2023-08-18', 1),
    ('Janki Devi Dharmshaktu', 'जानकी देवी धर्मशक्तू', 'F', 'Darkot', 'Munsiyari', 'Pithoragarh', 'Panchachuli Weavers SHG',
     'Rajma grower and weaver', 'राजमा उत्पादक और बुनकर', [('rajma', None), ('bhotia', None)], '2023-11-09', 1),
    ('Bhawan Singh Jalal', 'भवान सिंह जलाल', 'M', 'Kapkot', 'Kapkot', 'Bageshwar', 'Saryu Ghati Kisan Samooh',
     'Ringal weaver and chilli grower', 'रिंगाल शिल्पकार और मिर्च उत्पादक', [('ringal', None), ('lakhori', None)], '2024-09-14', 1),
    ('Rekha Rawat', 'रेखा रावत', 'F', 'Sarmoli', 'Munsiyari', 'Pithoragarh', 'Maati Sangathan SHG',
     'Rajma farmer', 'राजमा किसान', [('rajma', None)], '2023-10-05', 0),
]
INACTIVE_NOTE = 'Moved to Haldwani; supplied rajma until August 2026.'
INACTIVE_AFTER = date(2026, 8, 31)

# key: (name, hi, unit, cost, reorder, gi_keywords, source('vendor'|'member'), vendors/farmer keys)
V_COLOUR = 'Himgiri Colour Suppliers, Haldwani'
V_WOOD = 'Almora Timber & Craft Wood'
V_METAL = 'Naini Metals & Alloys, Haldwani'
V_PACK = 'Pahar Packaging Works, Rudrapur'
V_WOOL = 'Kumaon Wool Centre, Munsiyari'
V_CANVAS = 'Bhimtal Art & Canvas House'
V_DYE = 'Dharchula Natural Dye House'
V_RINGAL = 'Pithoragarh Ringal Depot'
RAW = {
    'geru': ('Geru (red ochre)', 'गेरू (लाल मिट्टी)', 'kg', 120, 3, ['aipan'], 'vendor', [V_COLOUR]),
    'biswar': ('Rice paste flour (biswar)', 'चावल का आटा (बिस्वार)', 'kg', 55, 4, ['aipan'], 'vendor', ['Almora Anaj Bhandar']),
    'canvas': ('Canvas sheet A3', 'कैनवास शीट (A3)', 'sheet', 85, 15, ['aipan'], 'vendor', [V_CANVAS]),
    'paper': ('Handmade paper sheet', 'हस्तनिर्मित कागज़ की शीट', 'sheet', 22, 40, ['aipan'], 'vendor', [V_CANVAS]),
    'plate': ('Wooden plate 12 inch', 'लकड़ी की थाली (12 इंच)', 'pcs', 110, 15, ['aipan'], 'vendor', [V_WOOD]),
    'chowki': ('Wooden chowki', 'लकड़ी की चौकी', 'pcs', 420, 6, ['aipan'], 'vendor', [V_WOOD]),
    'copper': ('Copper sheet', 'ताँबे की चादर', 'kg', 880, 5, ['tamta'], 'vendor', [V_METAL]),
    'tin': ('Tin for kalai (tinning)', 'कलई के लिए रांगा (टिन)', 'kg', 2100, 0.5, ['tamta'], 'vendor', [V_METAL]),
    'wool': ('Sheep wool (hand-spun)', 'भेड़ की ऊन (हाथ से काती)', 'kg', 420, 10, ['bhotia', 'thulma'], 'vendor', [V_WOOL]),
    'dye': ('Natural dye', 'प्राकृतिक रंग', 'kg', 650, 1, ['bhotia', 'thulma'], 'vendor', [V_DYE]),
    'rajma_raw': ('Raw Munsiyari rajma', 'कच्चा मुनस्यारी राजमा', 'kg', 160, 80, ['rajma'], 'member', ['rajma']),
    'tealeaf': ('Raw tea leaf', 'कच्ची चाय पत्ती', 'kg', 80, 30, ['berinag'], 'member', ['tea']),
    'chilli_raw': ('Raw Lakhori chilli (dried)', 'सूखी लखौरी मिर्च', 'kg', 380, 12, ['lakhori'], 'member', ['chilli']),
    'pouch500': ('Kraft pouch 500 g', 'क्राफ्ट पाउच 500 ग्राम', 'pcs', 4.5, 100, ['rajma'], 'vendor', [V_PACK]),
    'pouch1k': ('Kraft pouch 1 kg', 'क्राफ्ट पाउच 1 किग्रा', 'pcs', 6.5, 100, ['rajma'], 'vendor', [V_PACK]),
    'pouch100': ('Kraft pouch 100 g', 'क्राफ्ट पाउच 100 ग्राम', 'pcs', 3.2, 100, ['lakhori'], 'vendor', [V_PACK]),
    'tin100': ('Tea tin 100 g', 'चाय टिन 100 ग्राम', 'pcs', 24, 60, ['berinag'], 'vendor', [V_PACK]),
    'ringal': ('Ringal bamboo bundle', 'रिंगाल बाँस का बंडल', 'pcs', 150, 12, ['ringal'], 'vendor', [V_RINGAL]),
}
FARMERS = {  # purchase supplier keys -> member names
    'rajma': ['Kundan Singh Bora', 'Janki Devi Dharmshaktu', 'Rekha Rawat'],
    'tea': ['Lakshmi Kanyal', 'Narendra Singh Pangtey'],
    'chilli': ['Geeta Arya', 'Bhawan Singh Jalal', 'Lakshmi Kanyal'],
}

# gi kw, sku suffix, name, hi, unit, hsn, labour hours, labour rate, margin, bom, tier, popularity, lot, duration, shelf, desc, desc_hi
PRODUCTS = [
    ('aipan', 'WP12', 'Aipan Wall Plate (12 inch)', 'ऐपण वॉल प्लेट (12 इंच)', 'pcs', '4420', 2.5, 90, 25,
     {'plate': 1, 'geru': 0.05, 'biswar': 0.03}, 'mid', 3, (15, 30), (9, 16), None,
     'Wooden wall plate hand-painted with Aipan in geru and rice paste.',
     'लकड़ी की थाली पर गेरू और बिस्वार से हाथ से बना ऐपण।'),
    ('aipan', 'CV3', 'Aipan Canvas Painting (A3)', 'ऐपण कैनवास पेंटिंग (A3)', 'pcs', '9701', 3, 90, 25,
     {'canvas': 1, 'geru': 0.02, 'biswar': 0.02}, 'mid', 2, (12, 24), (9, 16), None,
     'Hand-painted Aipan on A3 canvas, ready to frame.',
     'A3 कैनवास पर हाथ से बनी ऐपण पेंटिंग।'),
    ('aipan', 'CH1', 'Aipan Puja Chowki', 'ऐपण पूजा चौकी', 'pcs', '4420', 5, 90, 25,
     {'chowki': 1, 'geru': 0.08, 'biswar': 0.05}, 'mid', 1.5, (8, 16), (10, 18), None,
     'Wooden puja chowki decorated with traditional Aipan.',
     'पारंपरिक ऐपण से सजी लकड़ी की पूजा चौकी।'),
    ('tamta', 'WB1', 'Copper Water Bottle (1 L)', 'ताँबे की पानी की बोतल (1 लीटर)', 'pcs', '7418', 5, 110, 30,
     {'copper': 0.42, 'tin': 0.01}, 'mid', 2, (10, 20), (10, 18), None,
     'Hand-hammered 1 litre copper bottle by Tamta craftsmen.',
     'टम्टा शिल्पकारों द्वारा हथौड़े से गढ़ी 1 लीटर की ताँबे की बोतल।'),
    ('tamta', 'GG1', 'Copper Gagar', 'ताँबे की गागर', 'pcs', '7418', 14, 110, 25,
     {'copper': 1.2, 'tin': 0.03}, 'high', 1, (4, 8), (14, 24), None,
     'Traditional copper gagar, hand-hammered and tin-lined.',
     'पारंपरिक ताँबे की गागर, हथौड़े से गढ़ी हुई और अंदर कलई की हुई।'),
    ('tamta', 'LT1', 'Copper Lota', 'ताँबे का लोटा', 'pcs', '7418', 2.5, 110, 25,
     {'copper': 0.3, 'tin': 0.01}, 'mid', 2, (15, 30), (8, 14), None,
     'Hand-made copper lota for daily and puja use.',
     'रोज़ और पूजा के उपयोग के लिए हाथ से बना ताँबे का लोटा।'),
    ('bhotia', 'RG35', 'Bhotia Dann Rug (3 x 5 ft)', 'भोटिया दन गलीचा (3 x 5 फीट)', 'pcs', '5701', 36, 90, 20,
     {'wool': 3.5, 'dye': 0.1}, 'high', 1, (3, 6), (18, 25), None,
     'Hand-woven woollen dann rug with traditional geometric design.',
     'पारंपरिक ज्यामितीय डिज़ाइन वाला हाथ से बुना ऊनी दन गलीचा।'),
    ('thulma', 'BL1', 'Thulma Blanket (single)', 'थुलमा कंबल (सिंगल)', 'pcs', '6301', 30, 80, 20,
     {'wool': 2.0, 'dye': 0.05}, 'high', 1, (3, 6), (16, 25), None,
     'Warm hand-woven woollen thulma, single bed size.',
     'हाथ से बुना गर्म ऊनी थुलमा, सिंगल बेड आकार।'),
    ('rajma', 'R500', 'Munsiyari White Rajma (500 g)', 'मुनस्यारी सफेद राजमा (500 ग्राम)', 'pack', '0713', 0.06, 80, 25,
     {'rajma_raw': 0.52, 'pouch500': 1}, 'low', 3, (80, 160), (6, 10), 365,
     'Cleaned and graded white rajma, 500 g pack.',
     'साफ और छँटा हुआ सफेद राजमा, 500 ग्राम पैक।'),
    ('rajma', 'R1K', 'Munsiyari White Rajma (1 kg)', 'मुनस्यारी सफेद राजमा (1 किग्रा)', 'pack', '0713', 0.1, 80, 25,
     {'rajma_raw': 1.04, 'pouch1k': 1}, 'low', 2, (60, 120), (6, 10), 365,
     'Cleaned and graded white rajma, 1 kg pack.',
     'साफ और छँटा हुआ सफेद राजमा, 1 किग्रा पैक।'),
    ('berinag', 'T100', 'Berinag Tea (100 g tin)', 'बेरीनाग चाय (100 ग्राम टिन)', 'pack', '0902', 1.2, 90, 30,
     {'tealeaf': 0.5, 'tin100': 1}, 'low', 2.5, (40, 80), (7, 12), 540,
     'Hand-processed Berinag tea in a 100 g tin.',
     'हाथ से तैयार की गई बेरीनाग चाय, 100 ग्राम टिन।'),
    ('lakhori', 'M100', 'Almora Lakhori Mirch (100 g)', 'अल्मोड़ा लखौरी मिर्च (100 ग्राम)', 'pack', '0904', 0.25, 80, 30,
     {'chilli_raw': 0.105, 'pouch100': 1}, 'low', 2, (60, 120), (6, 10), 365,
     'Dried Lakhori chilli from Almora, 100 g pack.',
     'अल्मोड़ा की सूखी लखौरी मिर्च, 100 ग्राम पैक।'),
    ('ringal', 'BK1', 'Ringal Basket', 'रिंगाल टोकरी', 'pcs', '4602', 4, 90, 25,
     {'ringal': 1}, 'mid', 1.5, (10, 20), (8, 14), None,
     'Hand-woven ringal (hill bamboo) basket.',
     'रिंगाल (पहाड़ी बाँस) से हाथ से बुनी टोकरी।'),
]

SHOP = 'Shop'
# name, type, contact, city, state, state_code, gstin pan (None -> no gstin), address
CUSTOMERS = [
    ('Naini Craft Emporium', 'retail', 'Rajesh Sah', 'Nainital', 'Uttarakhand', '05', 'AAGFN3391Q', 'Mall Road, Tallital, Nainital 263002'),
    ('Almora Bazaar Gift House', 'retail', 'Sunita Verma', 'Almora', 'Uttarakhand', '05', 'AAJFA7714K', 'Lala Bazaar, Almora 263601'),
    ('Ranikhet Hill Stores', 'retail', 'Prakash Negi', 'Ranikhet', 'Uttarakhand', '05', 'AAKFR2260L', 'Sadar Bazaar, Ranikhet 263645'),
    ('Mussoorie Mall Road Curios', 'retail', 'Anil Kapoor', 'Mussoorie', 'Uttarakhand', '05', 'AAHFM5532B', 'The Mall, Mussoorie 248179'),
    ('Dehradun Pahadi Haat', 'retail', 'Neeta Rawat', 'Dehradun', 'Uttarakhand', '05', 'AAMFD8815C', 'Rajpur Road, Dehradun 248001'),
    ('Haldwani Kumaon Kart', 'retail', 'Deepak Bisht', 'Haldwani', 'Uttarakhand', '05', 'AAPFH4107N', 'Nainital Road, Haldwani 263139'),
    ('Kausani Tea & Spice Shop', 'retail', 'Mamta Joshi', 'Kausani', 'Uttarakhand', '05', 'AAQFK6629R', 'Anasakti Ashram Road, Kausani 263639'),
    ('Deodar Gift Gallery', 'outlet', 'Ritu Bhatt', 'Nainital', 'Uttarakhand', '05', 'AAUFD1903E', 'Bara Bazaar, Nainital 263001'),
    ('Kumaon Vista Hotel Boutique', 'outlet', 'Manoj Pandey', 'Ranikhet', 'Uttarakhand', '05', 'AAWCK3375G', 'Upat Road, Ranikhet 263645'),
    ('Mall Road Souvenirs', 'outlet', 'Sanjay Thapliyal', 'Mussoorie', 'Uttarakhand', '05', 'AAXFM9048J', 'Library Chowk, Mussoorie 248179'),
    ('Capital Pahadi Traders', 'wholesale', 'Vikram Malhotra', 'New Delhi', 'Delhi', '07', 'AAECC5521P', 'Khan Market Road, New Delhi 110003'),
    ('Gomti Heritage Foods', 'wholesale', 'Farhan Siddiqui', 'Lucknow', 'Uttar Pradesh', '09', 'AAFCG7743D', 'Hazratganj, Lucknow 226001'),
    ('Bengaluru Himalayan Naturals', 'wholesale', 'Kavitha Rao', 'Bengaluru', 'Karnataka', '29', 'AAHCB2286M', 'Indiranagar 100 Feet Road, Bengaluru 560038'),
    ('Walk-in Customer', 'individual', None, 'Almora', 'Uttarakhand', '05', None, 'Counter / fair sales'),
    ('Online Store Buyer Account', 'online', 'Online orders', 'Online', 'Uttarakhand', '05', None, 'Orders received via the cooperative web shop'),
]

VENDOR_SUPPLY_TOP = 2.5
HOLD_LOW = ('copper', 'tin')  # not restocked in the last weeks, so they show up as low-stock alerts  # restock lot = reorder_level * this

SALE_MONTHS = [(2026, 6), (2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11)]
COUNTER_N = [8, 9, 11, 10, 12, 14]
WHOLESALE_N = [3, 3, 4, 4, 5, 5]
ONLINE_N = [2, 3, 3, 4, 5, 8]
GROWTH = {6: 0.9, 7: 1.0, 8: 1.1, 9: 1.25, 10: 1.4, 11: 1.6}
FAIRS = [  # name, start, end, invoices
    ('Hill Craft Haat, Nainital', date(2026, 8, 14), date(2026, 8, 16), 5),
    ('Nanda Devi Mela, Almora', date(2026, 9, 17), date(2026, 9, 22), 13),
    ('Dussehra Mela, Almora', date(2026, 10, 19), date(2026, 10, 21), 7),
    ('Diwali Utsav, Haldwani', date(2026, 11, 3), date(2026, 11, 7), 11),
]
# qty ranges (lo, hi) by channel and tier
QTY = {
    'counter': {'low': (1, 4), 'mid': (1, 2), 'high': (1, 1)},
    'fair': {'low': (1, 5), 'mid': (1, 3), 'high': (1, 1)},
    'online': {'low': (1, 3), 'mid': (1, 2), 'high': (1, 1)},
    'wholesale': {'low': (20, 60), 'mid': (5, 16), 'high': (1, 5)},
}
BASE_COVER = {'low': 100, 'mid': 20, 'high': 5}

INSPECTORS = ['GI Inspector – R. S. Negi', 'GI Inspector – Meena Bisht', 'Quality Officer – D. C. Pandey']
STUCK_AFTER = [date(2026, 9, 8), date(2026, 10, 1), date(2026, 10, 14)]
CANCEL_AFTER = date(2026, 8, 10)
REJECT_AFTER = date(2026, 8, 5)
REPLEN_STOP = date(2026, 11, 14)
PAYOUT_DAYS = []
_pd = date(2026, 6, 14)
while _pd <= SIM_END:
    PAYOUT_DAYS.append(_pd)
    _pd += timedelta(days=14)

CONSIGNMENTS = [
    # customer, sent, lines [(product sku suffix, qty)], sales [(date, fraction)], returns [(date, 'all'|fraction)]
    ('Deodar Gift Gallery', date(2026, 7, 6), [('WP12', 10), ('CV3', 6), ('LT1', 6), ('BK1', 6)],
     [(date(2026, 7, 29), 0.4), (date(2026, 8, 26), 0.3)], [(date(2026, 9, 12), 'all')]),
    ('Kumaon Vista Hotel Boutique', date(2026, 8, 12), [('WP12', 8), ('CV3', 5), ('CH1', 3), ('BL1', 2), ('LT1', 4)],
     [(date(2026, 9, 2), 0.35), (date(2026, 10, 4), 0.35)], [(date(2026, 10, 20), 0.2)]),
    ('Mall Road Souvenirs', date(2026, 9, 18), [('T100', 20), ('M100', 20), ('R500', 20), ('LT1', 4)],
     [(date(2026, 10, 12), 0.4), (date(2026, 11, 14), 0.25)], []),
    ('Deodar Gift Gallery', date(2026, 11, 3), [('WP12', 12), ('CV3', 6), ('CH1', 4), ('WB1', 4), ('T100', 24)],
     [(date(2026, 11, 15), 0.5)], []),
]
ADJUSTMENTS = [  # date, kind, key (raw key or sku suffix), qty, note
    (date(2026, 7, 22), 'raw', 'geru', 0.5, 'Spillage while grinding ochre'),
    (date(2026, 8, 19), 'raw', 'ringal', 3, 'Insect damage found at storage check'),
    (date(2026, 9, 24), 'prod', 'LT1', 2, 'Dented during transport to fair; written off'),
    (date(2026, 10, 2), 'raw', 'rajma_raw', 4.5, 'Stones and damaged beans removed during cleaning'),
    (date(2026, 10, 23), 'prod', 'WP12', 1, 'Plate cracked after fair; written off'),
    (date(2026, 11, 12), 'raw', 'wool', 1.2, 'Moth damage in wool store'),
]


# ------------------------------------------------------------------ builder

class Seeder:
    def __init__(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute('PRAGMA foreign_keys = ON')
        with open(SCHEMA, encoding='utf-8') as f:
            self.db.executescript(f.read())
        self.cur = self.db.cursor()
        self.warnings = []
        self.source = None

    def x(self, sql, args=()):
        self.cur.execute(sql, args)
        return self.cur.lastrowid

    # ---------- settings
    def seed_settings(self):
        for k, v in ORG.items():
            self.x('INSERT INTO settings(key,value) VALUES (?,?)', (k, v))

    # ---------- GI
    def seed_gi(self):
        if os.path.exists(GI_JSON):
            path, self.source = GI_JSON, 'real'
        elif os.path.exists(GI_JSON_PROV):
            path, self.source = GI_JSON_PROV, 'PROVISIONAL'
            bar = '!' * 78
            msg = ('data/uk_gi.json NOT FOUND - using PROVISIONAL GI list (names/categories only, '
                   'application numbers TEMP-n). Replace with real IP India data and re-run seed.py.')
            print(bar + '\n' + msg + '\n' + bar)
            self.warnings.append(msg)
        else:
            raise SystemExit('No GI data: data/uk_gi.json and data/uk_gi.provisional.json both missing')
        with open(path, encoding='utf-8') as f:
            rows = json.load(f)
        self.gis = []
        used_codes = set()
        seen = set()
        self.unmatched = []
        entries = []
        for r in rows:
            an = (r.get('application_number') or '').strip() if isinstance(r.get('application_number'), str) else r.get('application_number')
            an = str(an).strip() if an not in (None, '') else ''
            if not an or an in seen or not r.get('gi_name'):
                continue
            seen.add(an)
            entries.append((an, r, E.lookup(r['gi_name'])))
        # first pass: reserve enrichment codes
        for an, r, en in entries:
            if en and en['short_code'] not in used_codes:
                used_codes.add(en['short_code'])
                r['_code'] = en['short_code']
        for an, r, en in entries:
            code = r.get('_code')
            if not code:
                base = (norm(r['gi_name']).upper() + 'XXX')
                base = re.sub(r'[^A-Z]', '', base.replace('UTTARAKHAND', '')) or 'GIX'
                cands = [base[:3]] + [base[:2] + c for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ']
                code = next(c for c in cands if c not in used_codes)
                used_codes.add(code)
            if en:
                checklist = en['checklist']
                name_hi, desc_hi, ecat = en['name_hi'], en['description_hi'], en['category']
                desc_en = en['description']
            else:
                self.unmatched.append(r['gi_name'])
                checklist, name_hi, desc_hi, ecat = E.GENERIC_CHECKLIST, None, None, None
                desc_en = None
            cat = r.get('category') if r.get('category') in CATS else ecat  # Textiles -> Handicraft via enrichment
            urls = list(r.get('source_urls') or [])
            if en:
                urls += [u for u in en['sources'] if u not in urls]
            gid = self.x(
                '''INSERT INTO gi (application_number,name,name_hi,short_code,category,applicant_name,applicant_address,
                   date_of_filing,class,goods,geographical_area,priority_country,journal_number,availability_date,
                   certificate_number,certificate_date,valid_upto,status,description,description_hi,checklist,source_urls)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (an, r['gi_name'], name_hi, code, cat, r.get('applicant_name'), r.get('applicant_address'),
                 r.get('date_of_filing'), None if r.get('class') is None else str(r.get('class')), r.get('goods'),
                 r.get('geographical_area'), 'India', None if r.get('journal_number') is None else str(r.get('journal_number')),
                 r.get('availability_date'), r.get('certificate_number'), r.get('certificate_date'), r.get('valid_upto'),
                 r.get('status'), r.get('short_description') or desc_en, desc_hi,
                 json.dumps(checklist, ensure_ascii=False), json.dumps(urls, ensure_ascii=False)))
            self.gis.append({'id': gid, 'name': r['gi_name'], 'norm': norm(r['gi_name']), 'code': code,
                             'n_checks': len(checklist), 'checklist': checklist})

    def gi_kw(self, kw):
        for g in self.gis:
            if kw in g['norm']:
                return g
        return None

    # ---------- members
    def seed_members(self):
        self.members = {}
        self.member_by_name = {}
        for i, (name, hi, gender, village, block, dist, shg, skill, skill_hi, gis, joined, active) in enumerate(MEMBERS, 1):
            ph = phone()
            code = 'M-%03d' % i
            acct = ''.join(str(rng.randint(0, 9)) for _ in range(12))
            mid = self.x(
                '''INSERT INTO member (code,name,name_hi,gender,phone,village,block,district,shg_name,skill,skill_hi,
                   upi_id,bank_account,ifsc,joined_on,active,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (code, name, hi, gender, ph, village, block, dist, shg, skill, skill_hi,
                 ph + '@ybl' if i % 3 else None, acct if i % 2 == 0 else None,
                 'KZSB0000%03d' % rng.randint(100, 499) if i % 2 == 0 else None, joined, active,
                 None if active else INACTIVE_NOTE))
            m = {'id': mid, 'name': name, 'gender': gender, 'active': active, 'gi': {}, 'open': 0, 'last': 0,
                 'upi': bool(i % 3), 'credits': [], 'paid': 0.0}
            for kw, valid in gis:
                g = self.gi_kw(kw)
                if not g:
                    continue
                reg = D(joined) + timedelta(days=rng.randint(20, 90))
                vu = valid or '%d-03-31' % rng.choice([2029, 2030, 2031, 2032])
                self.x('INSERT INTO member_gi (member_id,gi_id,au_number,au_registered_on,au_valid_upto) VALUES (?,?,?,?,?)',
                       (mid, g['id'], 'AU/%s/%d/%04d' % (g['code'], reg.year, rng.randint(11, 989)), iso(reg), vu))
                m['gi'][g['id']] = D(vu)
            self.members[mid] = m
            self.member_by_name[name] = m

    # ---------- raw materials & products
    def seed_materials_products(self):
        self.rm = {}
        self.rm_key = {}
        self.raw_oh = {}
        n = 0
        # include only materials whose GI exists
        for key, (name, hi, unit, cost, reorder, kws, src, vend) in RAW.items():
            if not any(self.gi_kw(k) for k in kws):
                continue
            n += 1
            rid = self.x('INSERT INTO raw_material (code,name,name_hi,unit,cost_per_unit,reorder_level) VALUES (?,?,?,?,?,?)',
                         ('RM-%03d' % n, name, hi, unit, cost, reorder))
            self.rm[key] = {'id': rid, 'unit': unit, 'cost': cost, 'reorder': reorder, 'src': src, 'vend': vend, 'key': key}
            self.rm_key[rid] = key
            self.raw_oh[rid] = 0.0
        self.prods = {}
        self.prod_list = []
        for (kw, suf, name, hi, unit, hsn, hours, lrate, margin, bom, tier, pop, lot, dur, shelf, desc, desc_hi) in PRODUCTS:
            g = self.gi_kw(kw)
            if not g or any(k not in self.rm for k in bom):
                continue
            mat = r2(sum(self.rm[k]['cost'] * q for k, q in bom.items()))
            raw_price = (mat + hours * lrate) * 1.10 * (1 + margin / 100.0)
            price = 5 * round(raw_price / 5.0) if raw_price >= 30 else round(raw_price)
            lab = hours * lrate
            piece = 5 * round(lab / 5.0) if lab >= 30 else max(1, round(lab))
            sku = '%s-%s' % (g['code'], suf)
            pid = self.x(
                '''INSERT INTO product (sku,name,name_hi,gi_id,unit,hsn,gst_rate,price,piece_rate,material_cost,labour_hours,
                   labour_rate,overhead_pct,margin_pct,shelf_life_days,description,description_hi,active)
                   VALUES (?,?,?,?,?,?,5,?,?,?,?,?,10,?,?,?,?,1)''',
                (sku, name, hi, g['id'], unit, hsn, price, piece, mat, hours, lrate, margin, shelf, desc, desc_hi))
            for k, q in bom.items():
                self.x('INSERT INTO product_material (product_id,raw_material_id,qty_per_unit) VALUES (?,?,?)',
                       (pid, self.rm[k]['id'], q))
            p = {'id': pid, 'sku': sku, 'suf': suf, 'gi': g, 'name': name, 'price': float(price), 'piece': float(piece),
                 'tier': tier, 'pop': pop, 'lot': lot, 'dur': dur, 'shelf': shelf, 'unit': unit,
                 'bom': [(self.rm[k]['id'], q) for k, q in bom.items()], 'gst': 5.0, 'hours': hours}
            self.prods[pid] = p
            self.prod_list.append(p)
        self.by_suf = {p['suf']: p for p in self.prod_list}

    # ---------- customers
    def seed_customers(self):
        self.cust = {}
        for i, (name, typ, contact, city, state, sc, pan, addr) in enumerate(CUSTOMERS, 1):
            gst = gstin(sc, pan) if pan else None
            email = None if typ in ('individual',) else (norm(name)[:14] + '@' + ('gmail.com' if typ != 'wholesale' else 'business.in'))
            cid = self.x(
                '''INSERT INTO customer (code,name,type,contact_person,phone,email,gstin,address,city,state,state_code,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('C-%03d' % i, name, typ, contact, phone() if typ != 'individual' else None, email, gst, addr, city, state, sc,
                 'Consignment outlet' if typ == 'outlet' else None))
            self.cust[name] = {'id': cid, 'type': typ, 'sc': sc, 'name': name}

    # ---------- stock primitives
    def add_txn(self, d, item, qty, ref_type, ref_id=None, rm=None, batch=None, product=None, note=None):
        if item == 'raw':
            new = round(self.raw_oh[rm] + qty, 6)
            if new < -1e-9:
                raise RuntimeError('negative raw stock %s on %s' % (rm, d))
            self.raw_oh[rm] = new
        else:
            new = round(self.batch_oh[batch] + qty, 6)
            if new < -1e-9:
                raise RuntimeError('negative batch stock %s on %s' % (batch, d))
            self.batch_oh[batch] = new
        self.x('INSERT INTO stock_txn (date,item_type,raw_material_id,product_id,batch_id,qty,ref_type,ref_id,note) '
               'VALUES (?,?,?,?,?,?,?,?,?)', (iso(d), item, rm, product, batch, qty, ref_type, ref_id, note))

    def buy(self, d, rid, qty, member=None, supplier=None, notes=None):
        m = self.rm[self.rm_key[rid]]
        rate = r2(m['cost'] * rng.uniform(0.97, 1.05)) if m['unit'] != 'pcs' or m['cost'] > 20 else r2(m['cost'] * rng.uniform(0.97, 1.04))
        amount = r2(qty * rate)
        self.pur_n += 1
        pid = self.x('INSERT INTO purchase (purchase_no,date,raw_material_id,qty,rate,amount,member_id,supplier_name,notes) '
                     'VALUES (?,?,?,?,?,?,?,?,?)',
                     ('PUR-%04d' % self.pur_n, iso(d), rid, qty, rate, amount, member['id'] if member else None,
                      None if member else supplier, notes))
        self.add_txn(d, 'raw', qty, 'purchase', pid, rm=rid)
        if member:
            member['credits'].append((d, amount))
        self.purchases.append((d, rid, qty, amount))

    def ensure_raw(self, d, rid, need):
        have = self.raw_oh[rid]
        if have + 1e-9 >= need:
            return
        m = self.rm[self.rm_key[rid]]
        short = need - have
        lot = max(short, m['reorder'] * VENDOR_SUPPLY_TOP)
        if m['unit'] == 'kg' and m['cost'] < 1000 and m['reorder'] >= 1:
            lot = math.ceil(lot)
        elif m['unit'] == 'kg':
            lot = round(math.ceil(lot * 2) / 2.0, 1)
        else:
            lot = math.ceil(lot)
        if m['src'] == 'member':
            farmers = [self.member_by_name[n] for n in FARMERS[m['vend'][0]] if n in self.member_by_name]
            farmers = [f for f in farmers if f['active'] or d <= INACTIVE_AFTER]
            left = lot
            i = rng.randrange(len(farmers))
            while left > 1e-9:
                chunk = min(left, rng.choice([30, 40, 50, 60]) if m['key'] != 'chilli_raw' else rng.choice([8, 10, 12]))
                f = farmers[i % len(farmers)]
                self.buy(d, rid, chunk, member=f, notes='Delivered at society collection centre')
                left -= chunk
                i += 1
        else:
            self.buy(d, rid, lot, supplier=rng.choice(m['vend']))

    # ---------- batches
    def sellable(self, pid, d):
        return sum(self.batch_oh[b['id']] for b in self.batches_by_prod[pid]
                   if b['status'] == 'approved' and (b['expiry'] is None or b['expiry'] >= d))

    def pending(self, pid):
        return sum(self.batch_oh[b['id']] for b in self.batches_by_prod[pid] if b['status'] == 'pending')

    def fifo(self, pid, qty, d):
        cands = sorted([b for b in self.batches_by_prod[pid] if b['status'] == 'approved' and self.batch_oh[b['id']] > 0
                        and (b['expiry'] is None or b['expiry'] >= d)], key=lambda b: (b['mfg'], b['id']))
        out, left = [], qty
        for b in cands:
            if left <= 0:
                break
            q = min(left, self.batch_oh[b['id']])
            if q > 0:
                out.append((b, q))
                left -= q
        return out

    # ---------- work orders
    def eligible_members(self, p, d):
        out = []
        for m in self.members.values():
            vu = m['gi'].get(p['gi']['id'])
            if vu is None or vu < d or not m['active'] or m['open'] >= 2:
                continue
            out.append(m)
        return sorted(out, key=lambda m: (m['open'], m['last'], m['id']))

    def issue_wo(self, d, p, qty, member, first_wave=False, stuck=False, cancel_on=None):
        lo, hi = p['dur']
        base = rng.randint(lo, hi)
        if first_wave:
            base = min(base, 10 if p['tier'] != 'high' else 12)
        late = rng.random() < 0.15
        due = d + timedelta(days=hi if not first_wave else base)
        recv = d + timedelta(days=base + (rng.randint(1, 4) if late and not first_wave else 0))
        self.wo_n += 1
        wid = self.x('INSERT INTO work_order (wo_no,member_id,product_id,qty_ordered,issued_on,due_on,status,wage_rate,notes) '
                     'VALUES (?,?,?,?,?,?,?,?,?)',
                     ('WO-%04d' % self.wo_n, member['id'], p['id'], qty, iso(d), iso(due), 'issued', p['piece'], None))
        mats = []
        for rid, q in p['bom']:
            need = round(qty * q, 3)
            self.ensure_raw(d, rid, need)
            mid = self.x('INSERT INTO work_order_material (work_order_id,raw_material_id,qty_issued,qty_returned) VALUES (?,?,?,0)',
                         (wid, rid, need))
            self.add_txn(d, 'raw', -need, 'wo_issue', wid, rm=rid)
            mats.append({'row': mid, 'rid': rid, 'issued': need, 'qpu': q})
        member['open'] += 1
        member['last'] = self.wo_n
        wo = {'id': wid, 'product': p, 'member': member, 'qty': qty, 'issued': d, 'due': due, 'recv': recv,
              'mats': mats, 'stuck': stuck, 'cancel_on': cancel_on, 'done': False}
        self.wos.append(wo)
        return wo

    def receive_wo(self, d, wo):
        p, m = wo['product'], wo['member']
        qty = wo['qty']
        short = 0
        if p['tier'] == 'low' and rng.random() < 0.2:
            short = max(1, int(qty * rng.uniform(0.02, 0.05)))
        elif p['tier'] == 'mid' and rng.random() < 0.15:
            short = rng.randint(1, 2)
        received = qty - short
        for mt in wo['mats']:
            unit = self.rm[self.rm_key[mt['rid']]]['unit']
            unused = short * mt['qpu']
            if unit in ('kg', 'g', 'litre', 'metre'):
                unused += mt['issued'] * rng.choice([0, 0, 0.01, 0.02, 0.03])
                ret = round(min(mt['issued'], unused), 3)
            else:
                ret = float(min(mt['issued'], math.floor(unused + 1e-9)))
            if ret > 0:
                self.x('UPDATE work_order_material SET qty_returned=? WHERE id=?', (ret, mt['row']))
                self.add_txn(d, 'raw', ret, 'wo_return', wo['id'], rm=mt['rid'])
        # batch
        prefix = '%s-%s' % (p['gi']['code'], d.strftime('%y%m'))
        self.seq[prefix] += 1
        batch_no = '%s-%03d' % (prefix, self.seq[prefix])
        expiry = d + timedelta(days=p['shelf']) if p['shelf'] else None
        bid = self.x(
            '''INSERT INTO batch (batch_no,product_id,gi_id,member_id,work_order_id,qty,mfg_date,expiry_date,serial_from,serial_to,
               status,checklist_result) VALUES (?,?,?,?,?,?,?,?,?,?, 'pending','[]')''',
            (batch_no, p['id'], p['gi']['id'], m['id'], wo['id'], received, iso(d), iso(expiry),
             batch_no + '-001', '%s-%03d' % (batch_no, received)))
        b = {'id': bid, 'no': batch_no, 'product': p, 'mfg': d, 'expiry': expiry, 'status': 'pending', 'qty': received}
        self.batch_oh[bid] = 0.0
        self.batches_by_prod[p['id']].append(b)
        self.batches.append(b)
        self.add_txn(d, 'product', received, 'production', bid, batch=bid, product=p['id'])
        wage = r2(received * p['piece'])
        self.x('UPDATE work_order SET status=?, qty_received=?, received_on=?, wage_amount=?, batch_id=? WHERE id=?',
               ('completed', received, iso(d), wage, bid, wo['id']))
        m['credits'].append((d, wage))
        m['open'] -= 1
        wo['done'] = True
        self.insp_queue[d + timedelta(days=rng.randint(2, 3))].append(b)

    def cancel_wo(self, d, wo):
        for mt in wo['mats']:
            self.x('UPDATE work_order_material SET qty_returned=? WHERE id=?', (mt['issued'], mt['row']))
            self.add_txn(d, 'raw', mt['issued'], 'wo_return', wo['id'], rm=mt['rid'])
        self.x("UPDATE work_order SET status='cancelled', notes=? WHERE id=?",
               ('Cancelled: member unavailable for the festival season; materials returned to store', wo['id']))
        wo['member']['open'] -= 1
        wo['done'] = True
        wo['cancelled'] = True

    def inspect(self, d, b):
        g = b['product']['gi']
        n = g['n_checks']
        res = [True] * n
        notes = None
        if not self.rejected_done and b['mfg'] >= REJECT_AFTER and b['product']['tier'] == 'mid' and n >= 2:
            idx = 2 if n > 2 else 1
            res[idx] = False
            item = g['checklist'][idx]['en']
            notes = 'Rejected: failed check "%s". Batch held in store; not released for sale.' % item
            b['status'] = 'rejected'
            self.rejected_done = True
        else:
            b['status'] = 'approved'
            notes = rng.choice(['All checklist points satisfied.', None, None, 'Checked against GI specification; approved.'])
        pub = None
        if b['status'] == 'approved' and rng.random() < 0.6:
            pd = d + timedelta(days=rng.randint(1, 6))
            pub = iso(pd) if pd <= SIM_END else None
        self.x('UPDATE batch SET status=?, checklist_result=?, inspected_by=?, inspected_on=?, inspection_notes=?, published_on=? WHERE id=?',
               (b['status'], json.dumps(res), rng.choice(INSPECTORS), iso(d), notes, pub, b['id']))

    # ---------- replenishment
    def replenish(self, d, first_day):
        if d > REPLEN_STOP:
            return
        issued_today = 0
        for p in self.prod_list:
            if issued_today >= 2 and not first_day:
                break
            open_ = [w for w in self.wos if not w['done'] and not w['stuck'] and w['product'] is p]
            if len(open_) >= 2:
                continue
            trailing = sum(q for (dd, q) in self.sales_hist[p['id']] if (d - dd).days <= 30)
            target = max(BASE_COVER[p['tier']], 1.3 * trailing)
            pos = self.sellable(p['id'], d) + self.pending(p['id']) + sum(w['qty'] for w in open_)
            if pos >= target:
                continue
            mems = self.eligible_members(p, d)
            if not mems:
                continue
            qty = rng.randint(*p['lot'])
            if p['tier'] == 'high':
                qty = min(qty, 4 if first_day else qty)
            stuck = False
            cancel_on = None
            if self.stuck_idx < len(STUCK_AFTER) and d >= STUCK_AFTER[self.stuck_idx] and p['tier'] != 'low':
                stuck = True
                self.stuck_idx += 1
            elif not self.cancel_done and d >= CANCEL_AFTER and p['tier'] in ('mid', 'high'):
                cancel_on = d + timedelta(days=4)
                self.cancel_done = True
            self.issue_wo(d, p, qty, mems[0], first_wave=first_day, stuck=stuck, cancel_on=cancel_on)
            issued_today += 1

    # ---------- sales
    def create_sale(self, d, cust, channel, lines, venue=None, consignment_id=None, notes=None):
        """lines: [(product, batch, qty, rate)]"""
        c = self.cust[cust] if isinstance(cust, str) else cust
        inter = 1 if c['sc'] != ORG_STATE_CODE else 0
        self.inv_n += 1
        inv = 'INV/%s/%04d' % ('2026-27', self.inv_n)
        calc = []
        for p, b, q, rate in lines:
            taxable = r2(q * rate)
            tax = r2(taxable * p['gst'] / 100.0)
            calc.append((p, b, q, rate, taxable, tax, r2(taxable + tax)))
        sub = r2(sum(c_[4] for c_ in calc))
        tt = r2(sum(c_[5] for c_ in calc))
        sid = self.x('INSERT INTO sale (invoice_no,date,customer_id,channel,venue,is_interstate,subtotal,tax_total,total,consignment_id,notes) '
                     'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                     (inv, iso(d), c['id'], channel, venue, inter, sub, tt, r2(sub + tt), consignment_id, notes))
        for p, b, q, rate, taxable, tax, amt in calc:
            self.x('INSERT INTO sale_line (sale_id,product_id,batch_id,qty,rate,gst_rate,taxable,tax,amount) VALUES (?,?,?,?,?,?,?,?,?)',
                   (sid, p['id'], b['id'], q, rate, p['gst'], taxable, tax, amt))
            if channel != 'consignment':
                self.add_txn(d, 'product', -q, 'sale', sid, batch=b['id'], product=p['id'])
            self.sales_hist[p['id']].append((d, q))
        rec = {'id': sid, 'date': d, 'channel': channel, 'cust': c, 'total': r2(sub + tt), 'inv': inv}
        self.sale_recs.append(rec)
        return rec

    def run_planned_sale(self, d, channel, venue):
        gm = GROWTH[d.month]
        if channel in ('counter', 'fair'):
            c = self.cust['Walk-in Customer']
        elif channel == 'online':
            c = self.cust['Online Store Buyer Account']
        else:
            pool = [x for x in self.cust.values() if x['type'] in ('retail', 'wholesale')]
            w = [3 if x['type'] == 'wholesale' else 1.5 for x in pool]
            c = rng.choices(pool, weights=w)[0]
        avail = [p for p in self.prod_list if self.sellable(p['id'], d) > 0]
        if not avail:
            return
        k = {'counter': rng.randint(1, 3), 'fair': rng.randint(1, 4), 'online': rng.randint(1, 3),
             'wholesale': rng.randint(2, 5)}[channel]
        k = min(k, len(avail))
        chosen = []
        pool = list(avail)
        for _ in range(k):
            pick = rng.choices(pool, weights=[p['pop'] for p in pool])[0]
            chosen.append(pick)
            pool.remove(pick)
        lines = []
        for p in chosen:
            lo, hi = QTY[channel][p['tier']]
            q = rng.randint(lo, hi)
            if channel == 'wholesale':
                q = max(1, int(round(q * gm)))
            elif p['tier'] == 'low' and gm > 1.2 and rng.random() < 0.5:
                q += 1
            rate = p['price']
            if channel == 'wholesale':
                rate = float(round(p['price'] * (0.90 if c['type'] == 'wholesale' else 0.93)))
            for b, qq in self.fifo(p['id'], q, d):
                lines.append((p, b, int(qq), rate))
        if lines:
            self.create_sale(d, c, channel, lines, venue=venue)

    # ---------- consignments
    def send_consignment(self, d, spec, idx):
        cust, sent, lines, sales, rets = spec
        c = self.cust[cust]
        cl = []
        for suf, qty in lines:
            p = self.by_suf.get(suf)
            if not p:
                continue
            for b, q in self.fifo(p['id'], qty, d):
                cl.append((p, b, int(q)))
        if not cl:
            return
        self.cn_n += 1
        cid = self.x('INSERT INTO consignment (cn_no,customer_id,sent_on,status,notes) VALUES (?,?,?,?,?)',
                     ('CN-%04d' % self.cn_n, c['id'], iso(d), 'open', 'Sent by courier with delivery challan'))
        rec = {'id': cid, 'cust': c, 'lines': [], 'spec': spec}
        for p, b, q in cl:
            rate = float(round(p['price'] * 0.88))
            lid = self.x('INSERT INTO consignment_line (consignment_id,product_id,batch_id,qty_sent,qty_sold,qty_returned,rate) '
                         'VALUES (?,?,?,?,0,0,?)', (cid, p['id'], b['id'], q, rate))
            self.add_txn(d, 'product', -q, 'consignment_out', cid, batch=b['id'], product=p['id'])
            rec['lines'].append({'id': lid, 'p': p, 'b': b, 'sent': q, 'sold': 0, 'ret': 0, 'rate': rate})
        self.cns[idx] = rec

    def cn_settle_check(self, rec):
        if all(l['sent'] == l['sold'] + l['ret'] for l in rec['lines']):
            self.x("UPDATE consignment SET status='settled' WHERE id=?", (rec['id'],))

    def cn_sale(self, d, rec, frac):
        lines = []
        for l in rec['lines']:
            rem = l['sent'] - l['sold'] - l['ret']
            q = min(rem, int(round(l['sent'] * frac)))
            if q > 0:
                lines.append((l, q))
        if not lines:
            return
        s = self.create_sale(d, rec['cust'], 'consignment', [(l['p'], l['b'], q, l['rate']) for l, q in lines],
                             consignment_id=rec['id'], notes='Sale recorded against consignment')
        for l, q in lines:
            l['sold'] += q
            self.x('UPDATE consignment_line SET qty_sold=? WHERE id=?', (l['sold'], l['id']))
        self.cn_settle_check(rec)

    def cn_return(self, d, rec, how):
        for l in rec['lines']:
            rem = l['sent'] - l['sold'] - l['ret']
            q = rem if how == 'all' else min(rem, int(l['sent'] * how))
            if q > 0:
                l['ret'] += q
                self.x('UPDATE consignment_line SET qty_returned=? WHERE id=?', (l['ret'], l['id']))
                self.add_txn(d, 'product', q, 'consignment_return', rec['id'], batch=l['b']['id'], product=l['p']['id'])
        self.cn_settle_check(rec)

    # ---------- adjustments
    def adjust(self, d, kind, key, qty, note):
        if kind == 'raw':
            if key not in self.rm:
                return
            rid = self.rm[key]['id']
            q = min(qty, self.raw_oh[rid])
            if q > 0:
                self.add_txn(d, 'raw', -q, 'adjustment', None, rm=rid, note=note)
        else:
            p = self.by_suf.get(key)
            if not p:
                return
            cands = [b for b in self.batches_by_prod[p['id']] if b['status'] == 'approved' and self.batch_oh[b['id']] >= qty]
            if cands:
                b = cands[-1]
                self.add_txn(d, 'product', -qty, 'adjustment', None, batch=b['id'], product=p['id'], note=note)

    # ---------- payouts
    def run_payouts(self, d):
        for m in self.members.values():
            earned = sum(a for (dd, a) in m['credits'] if dd <= d)
            bal = earned - m['paid']
            if bal < 300 or rng.random() < 0.15:
                continue
            frac = 1.0 if (not m['active'] and d > INACTIVE_AFTER) else rng.uniform(0.6, 0.95)
            amt = math.floor(bal * frac / 10.0) * 10
            if not m['active'] and d > INACTIVE_AFTER:
                amt = math.floor(bal)
            if amt <= 0:
                continue
            mode = 'upi' if m['upi'] and rng.random() < 0.8 else rng.choice(['cash', 'bank'] if not m['upi'] else ['cash'])
            ref = 'UPI%s' % ''.join(str(rng.randint(0, 9)) for _ in range(12)) if mode == 'upi' else (
                'NEFT%s' % ''.join(str(rng.randint(0, 9)) for _ in range(10)) if mode == 'bank' else None)
            self.x('INSERT INTO payout (date,member_id,amount,mode,reference,notes) VALUES (?,?,?,?,?,?)',
                   (iso(d), m['id'], float(amt), mode, ref, 'Fortnightly wages and produce payment'))
            m['paid'] += amt

    # ---------- payments
    def gen_payments(self):
        sales = self.sale_recs
        b2b = [s for s in sales if s['channel'] in ('wholesale', 'consignment')]
        old = [s for s in b2b if s['date'] <= date(2026, 10, 18)]
        recent = [s for s in sales if s['date'] >= date(2026, 11, 8)]
        unpaid = set()
        for s in rng.sample(old, min(4, len(old))):
            unpaid.add(s['id'])
        recent_b2b = [s for s in recent if s['channel'] in ('wholesale', 'consignment')]
        for s in recent_b2b[:6]:
            unpaid.add(s['id'])
        extra = [s for s in recent if s['id'] not in unpaid and s['channel'] in ('online',)]
        for s in extra[:12 - len(unpaid)]:
            unpaid.add(s['id'])
        rest = [s for s in b2b if s['id'] not in unpaid]
        partial = set(s['id'] for s in rng.sample(rest, min(9, len(rest))))
        pays = []

        def mk_ref(mode):
            if mode == 'upi':
                return 'UPI%s' % ''.join(str(rng.randint(0, 9)) for _ in range(12))
            if mode == 'bank':
                return 'NEFT%s' % ''.join(str(rng.randint(0, 9)) for _ in range(10))
            if mode == 'cheque':
                return 'CHQ %06d' % rng.randint(100000, 999999)
            return None

        for s in sales:
            if s['id'] in unpaid:
                continue
            tot = s['total']
            ch = s['channel']
            if ch in ('counter', 'fair'):
                mode = rng.choice(['cash', 'upi'])
                pays.append((s['date'], s['id'], s['cust']['id'], tot, mode, mk_ref(mode)))
                continue
            if ch == 'online':
                pays.append((s['date'], s['id'], s['cust']['id'], tot, 'upi', mk_ref('upi')))
                continue
            lag = rng.randint(3, 28) if ch == 'wholesale' else rng.randint(5, 20)
            pdate = min(s['date'] + timedelta(days=lag), SIM_END)
            mode = rng.choice(['bank', 'bank', 'upi', 'cheque'])
            if s['id'] in partial:
                amt = r2(math.floor(tot * rng.uniform(0.4, 0.7) / 10.0) * 10)
                pays.append((pdate, s['id'], s['cust']['id'], amt, mode, mk_ref(mode)))
            elif ch == 'wholesale' and rng.random() < 0.3 and tot > 5000:
                adv = r2(math.floor(tot * 0.5))
                pays.append((s['date'], s['id'], s['cust']['id'], adv, 'upi', mk_ref('upi')))
                pays.append((pdate, s['id'], s['cust']['id'], r2(tot - adv), mode, mk_ref(mode)))
            else:
                pays.append((pdate, s['id'], s['cust']['id'], tot, mode, mk_ref(mode)))
        pays.sort(key=lambda r: (r[0], r[1]))
        for dte, sid, cid, amt, mode, ref in pays:
            self.x('INSERT INTO payment_in (date,sale_id,customer_id,amount,mode,reference,notes) VALUES (?,?,?,?,?,?,?)',
                   (iso(dte), sid, cid, amt, mode, ref, None))

    # ---------- main simulation
    def simulate(self):
        self.batch_oh = {}
        self.batches = []
        self.batches_by_prod = defaultdict(list)
        self.wos = []
        self.wo_n = self.pur_n = self.inv_n = self.cn_n = 0
        self.purchases = []
        self.seq = defaultdict(int)
        self.insp_queue = defaultdict(list)
        self.sales_hist = defaultdict(list)
        self.sale_recs = []
        self.cns = {}
        self.rejected_done = False
        self.cancel_done = False
        self.stuck_idx = 0
        # sales plan
        plan = defaultdict(list)

        def spread(n, lo, hi):
            span = (hi - lo).days
            return [lo + timedelta(days=rng.randint(0, span)) for _ in range(n)]

        for i, (y, mth) in enumerate(SALE_MONTHS):
            lo = date(y, mth, 1)
            hi = date(y, mth + 1, 1) - timedelta(days=1) if mth < 12 else date(y, 12, 31)
            hi = min(hi, SIM_END)
            lo = max(lo, date(2026, 6, 12))
            for dd in spread(COUNTER_N[i], lo, hi):
                plan[dd].append(('counter', None))
            wlo, whi = lo, hi
            if mth == 11:
                whi = date(2026, 11, 14)
            for dd in spread(WHOLESALE_N[i], wlo, whi):
                plan[dd].append(('wholesale', None))
            for dd in spread(ONLINE_N[i], lo, hi):
                plan[dd].append(('online', None))
        for name, s, e, n in FAIRS:
            for dd in spread(n, s, e):
                plan[dd].append(('fair', name))
        # Diwali (8 Nov) rush: extra counter/online sales Nov 1-8
        for dd in spread(6, date(2026, 11, 1), date(2026, 11, 8)):
            plan[dd].append(('counter', None))
        for dd in spread(4, date(2026, 11, 2), date(2026, 11, 8)):
            plan[dd].append(('online', None))
        cn_send = {}
        cn_sales = defaultdict(list)
        cn_rets = defaultdict(list)
        for i, spec in enumerate(CONSIGNMENTS):
            if spec[0] not in self.cust:
                continue
            cn_send[spec[1]] = (i, spec)
            for dd, fr in spec[3]:
                cn_sales[dd].append((i, fr))
            for dd, how in spec[4]:
                cn_rets[dd].append((i, how))
        adj = defaultdict(list)
        for a in ADJUSTMENTS:
            adj[a[0]].append(a[1:])

        d = SIM_START
        first = True
        while d <= SIM_END:
            for wo in [w for w in self.wos if not w['done'] and not w['stuck'] and not w['cancel_on'] and w['recv'] == d]:
                self.receive_wo(d, wo)
            for wo in [w for w in self.wos if not w['done'] and w['cancel_on'] == d]:
                self.cancel_wo(d, wo)
            for b in self.insp_queue.pop(d, []):
                self.inspect(d, b)
            for a in adj.get(d, []):
                self.adjust(d, *a)
            if d.weekday() == 0 and d > SIM_START:
                for key, m in self.rm.items():
                    if key in HOLD_LOW and d >= date(2026, 11, 2):
                        continue
                    if self.raw_oh[m['id']] < m['reorder']:
                        self.ensure_raw(d, m['id'], m['reorder'] * VENDOR_SUPPLY_TOP)
            self.replenish(d, first)
            first = False
            if d in cn_send:
                i, spec = cn_send[d]
                self.send_consignment(d, spec, i)
            for i, fr in cn_sales.get(d, []):
                if i in self.cns:
                    self.cn_sale(d, self.cns[i], fr)
            for i, how in cn_rets.get(d, []):
                if i in self.cns:
                    self.cn_return(d, self.cns[i], how)
            for ch, venue in plan.get(d, []):
                self.run_planned_sale(d, ch, venue)
            if d in PAYOUT_DAYS:
                self.run_payouts(d)
            d += timedelta(days=1)
        # leftover inspections past the end remain pending (as intended)
        self.gen_payments()

    def finalize(self):
        # leave 1-2 materials below reorder level
        done = 0
        for key in ('copper', 'tin', 'pouch500', 'tin100'):
            if key in self.rm and done < 2:
                m = self.rm[key]
                oh = self.raw_oh[m['id']]
                if oh >= m['reorder']:
                    newlvl = math.ceil(oh * 1.4 + 2) if m['unit'] != 'kg' or oh > 3 else round(oh * 1.5 + 0.5, 1)
                    self.x('UPDATE raw_material SET reorder_level=? WHERE id=?', (newlvl, m['id']))
                done += 1
        self.db.commit()


# ------------------------------------------------------------------ consistency checks

def run_checks(db):
    errs = []
    q = lambda sql, a=(): db.execute(sql, a).fetchall()

    def chk(cond, msg):
        if not cond:
            errs.append(msg)

    # views
    for v in ('v_raw_stock', 'v_batch_stock', 'v_product_stock', 'v_member_ledger', 'v_member_balance', 'v_sale_status',
              'v_customer_balance'):
        try:
            q('SELECT * FROM %s' % v)
        except Exception as e:
            errs.append('view %s failed: %s' % (v, e))
    # running stock
    run = defaultdict(float)
    for r in q('SELECT date,item_type,raw_material_id,batch_id,qty,id FROM stock_txn ORDER BY date,id'):
        key = ('r', r[2]) if r[1] == 'raw' else ('b', r[3])
        run[key] += r[4]
        chk(run[key] > -1e-6, 'negative stock %s on %s' % (key, r[0]))
        chk((r[1] == 'raw') == (r[2] is not None) and (r[1] == 'product') == (r[3] is not None), 'stock_txn key mismatch %s' % r[5])
    # sales
    for s in q('SELECT id,invoice_no,subtotal,tax_total,total,customer_id,is_interstate FROM sale'):
        lines = q('SELECT qty,rate,gst_rate,taxable,tax,amount,batch_id FROM sale_line WHERE sale_id=?', (s[0],))
        chk(lines, 'sale %s has no lines' % s[1])
        for l in lines:
            chk(abs(l[0] * l[1] - l[3]) < 0.011 and abs(l[3] * l[2] / 100 - l[4]) < 0.011 and abs(l[3] + l[4] - l[5]) < 0.011,
                'line math %s' % s[1])
            chk(float(l[0]).is_integer(), 'fractional qty in %s' % s[1])
        chk(abs(sum(l[3] for l in lines) - s[2]) < 0.011, 'subtotal %s' % s[1])
        chk(abs(sum(l[4] for l in lines) - s[3]) < 0.011, 'tax_total %s' % s[1])
        chk(abs(s[2] + s[3] - s[4]) < 0.011, 'total %s' % s[1])
        bs = [l[6] for l in lines]
        chk(len(bs) == len(set(bs)), 'duplicate batch lines in %s' % s[1])
    invs = [r[0] for r in q('SELECT invoice_no FROM sale ORDER BY date,id')]
    chk(invs == ['INV/2026-27/%04d' % i for i in range(1, len(invs) + 1)], 'invoice numbers not sequential by date')
    for r in q('SELECT s.invoice_no, c.state_code, s.is_interstate FROM sale s JOIN customer c ON c.id=s.customer_id'):
        chk(r[2] == (1 if r[1] != '05' else 0), 'interstate flag %s' % r[0])
    # sold batches approved & unexpired at date
    for r in q('''SELECT s.invoice_no,s.date,b.status,b.inspected_on,b.expiry_date FROM sale s JOIN sale_line l ON l.sale_id=s.id
                  JOIN batch b ON b.id=l.batch_id'''):
        chk(r[2] == 'approved' and r[3] is not None and r[3] <= r[1], 'sale %s from non-approved batch' % r[0])
        chk(r[4] is None or r[4] >= r[1], 'sale %s from expired batch' % r[0])
    # payments
    for r in q('SELECT invoice_no,total,paid,due FROM v_sale_status'):
        chk(r[3] >= -0.005, 'overpaid %s' % r[0])
    for r in q('SELECT p.id FROM payment_in p JOIN sale s ON s.id=p.sale_id WHERE p.customer_id<>s.customer_id OR p.date<s.date'):
        errs.append('payment %s inconsistent' % r[0])
    # consignments
    for r in q('SELECT id,consignment_id,product_id,batch_id,qty_sent,qty_sold,qty_returned FROM consignment_line'):
        chk(r[4] >= r[5] + r[6], 'consignment line %s oversold' % r[0])
        sold = db.execute('SELECT COALESCE(SUM(l.qty),0) FROM sale_line l JOIN sale s ON s.id=l.sale_id WHERE s.consignment_id=? AND l.batch_id=?',
                          (r[1], r[3])).fetchone()[0]
        chk(abs(sold - r[5]) < 1e-9, 'consignment line %s sold mismatch' % r[0])
        out = db.execute("SELECT COALESCE(SUM(qty),0) FROM stock_txn WHERE ref_type='consignment_out' AND ref_id=? AND batch_id=?", (r[1], r[3])).fetchone()[0]
        ret = db.execute("SELECT COALESCE(SUM(qty),0) FROM stock_txn WHERE ref_type='consignment_return' AND ref_id=? AND batch_id=?", (r[1], r[3])).fetchone()[0]
        chk(abs(-out - r[4]) < 1e-9 and abs(ret - r[6]) < 1e-9, 'consignment stock txn mismatch line %s' % r[0])
    for c in q('SELECT id,status FROM consignment'):
        done = db.execute('SELECT COUNT(*) FROM consignment_line WHERE consignment_id=? AND qty_sent<>qty_sold+qty_returned', (c[0],)).fetchone()[0] == 0
        chk((c[1] == 'settled') == done, 'consignment %s status' % c[0])
    for r in q("SELECT COUNT(*) FROM sale WHERE channel='consignment' AND consignment_id IS NULL"):
        chk(r[0] == 0, 'consignment sale without consignment_id')
    chk(db.execute("SELECT COUNT(*) FROM stock_txn t JOIN sale s ON s.id=t.ref_id WHERE t.ref_type='sale' AND s.channel='consignment'").fetchone()[0] == 0,
        'stock txn recorded for consignment sale')
    # work orders
    for w in q('SELECT id,wo_no,member_id,product_id,qty_ordered,issued_on,status,qty_received,wage_rate,wage_amount,batch_id,received_on FROM work_order'):
        if w[6] == 'completed':
            chk(abs(w[7] * w[8] - w[9]) < 0.011, 'wage math %s' % w[1])
            chk(0 < w[7] <= w[4], 'qty_received %s' % w[1])
            b = db.execute('SELECT qty,mfg_date FROM batch WHERE id=?', (w[10],)).fetchone()
            chk(b and b[0] == w[7] and b[1] == w[11], 'batch/wo mismatch %s' % w[1])
        else:
            chk(w[9] == 0 and w[10] is None, 'non-completed WO has wage/batch %s' % w[1])
        au = db.execute('''SELECT mg.au_valid_upto FROM member_gi mg JOIN product p ON p.gi_id=mg.gi_id
                           WHERE mg.member_id=? AND p.id=?''', (w[2], w[3])).fetchone()
        chk(au is not None and au[0] >= w[5], 'WO %s member not authorised' % w[1])
    for r in q('SELECT work_order_id,qty_issued,qty_returned FROM work_order_material'):
        chk(r[2] <= r[1] + 1e-9, 'return > issue WO %s' % r[0])
    for r in q("SELECT w.wo_no FROM work_order w JOIN work_order_material m ON m.work_order_id=w.id WHERE w.status='cancelled' AND abs(m.qty_issued-m.qty_returned)>1e-9"):
        errs.append('cancelled WO %s not fully returned' % r[0])
    # batches
    rx = re.compile(r'^[A-Z]{3,4}-\d{4}-\d{3}$')
    for b in q('SELECT b.batch_no,b.qty,b.serial_from,b.serial_to,b.mfg_date,b.expiry_date,p.shelf_life_days,b.status,b.checklist_result,g.checklist,b.product_id FROM batch b JOIN product p ON p.id=b.product_id JOIN gi g ON g.id=b.gi_id'):
        chk(rx.match(b[0]) is not None, 'batch_no format %s' % b[0])
        chk(b[2] == b[0] + '-001' and b[3] == '%s-%03d' % (b[0], b[1]), 'serials %s' % b[0])
        chk((b[6] is None) == (b[5] is None), 'expiry %s' % b[0])
        if b[6]:
            chk(D(b[5]) == D(b[4]) + timedelta(days=b[6]), 'expiry calc %s' % b[0])
        if b[7] != 'pending':
            chk(len(json.loads(b[8])) == len(json.loads(b[9])), 'checklist length %s' % b[0])
    # numbering formats
    for table, col, pat in (('purchase', 'purchase_no', r'^PUR-\d{4}$'), ('work_order', 'wo_no', r'^WO-\d{4}$'),
                            ('consignment', 'cn_no', r'^CN-\d{4}$'), ('member', 'code', r'^M-\d{3}$'),
                            ('customer', 'code', r'^C-\d{3}$'), ('raw_material', 'code', r'^RM-\d{3}$'),
                            ('sale', 'invoice_no', r'^INV/\d{4}-\d{2}/\d{4}$')):
        for (v,) in q('SELECT %s FROM %s' % (col, table)):
            chk(re.match(pat, v) is not None, '%s format %s' % (table, v))
    for r in q('SELECT p.purchase_no FROM purchase p WHERE abs(p.qty*p.rate-p.amount)>0.011'):
        errs.append('purchase amount %s' % r[0])
    # payouts never exceed ledger balance at date
    for m in q('SELECT id FROM member'):
        led = q('SELECT date,credit,debit FROM v_member_ledger WHERE member_id=? ORDER BY date, debit', (m[0],))
        bal = 0.0
        for dte, cr, de in led:
            bal += cr - de
            chk(bal > -0.01, 'member %s balance negative on %s' % (m[0], dte))
    # product consistency
    for p in q('SELECT sku,unit FROM product'):
        chk(p[1] in ('pcs', 'pack', 'set'), 'product unit %s' % p[0])
    return errs


# ------------------------------------------------------------------ summary

def summary(S):
    db = S.db
    q = lambda sql, a=(): db.execute(sql, a).fetchall()
    print('\n' + '=' * 78)
    print('SEED SUMMARY   db=%s   GI source: %s' % (DB_PATH, S.source))
    print('=' * 78)
    for t in ('gi', 'member', 'member_gi', 'raw_material', 'product', 'product_material', 'purchase', 'customer', 'work_order',
              'work_order_material', 'batch', 'stock_txn', 'consignment', 'consignment_line', 'sale', 'sale_line',
              'payment_in', 'payout'):
        print('  %-20s %6d' % (t, db.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0]))
    print('\nRevenue by month (taxable / incl. GST / invoices):')
    for r in q("SELECT substr(date,1,7), SUM(subtotal), SUM(total), COUNT(*) FROM sale GROUP BY 1 ORDER BY 1"):
        print('  %s  %12.2f  %12.2f  %4d' % r)
    print('Revenue by channel:')
    for r in q('SELECT channel, COUNT(*), ROUND(SUM(total),2) FROM sale GROUP BY 1'):
        print('  %-12s %4d  %12.2f' % r)
    tot = db.execute('SELECT COALESCE(SUM(due),0), SUM(due>0.005), SUM(pay_status="unpaid"), SUM(pay_status="partial") FROM v_sale_status').fetchone()
    old = db.execute("SELECT COUNT(*), COALESCE(SUM(due),0) FROM v_sale_status WHERE pay_status='unpaid' AND date<='2026-10-22'").fetchone()
    print('\nReceivables: Rs %.2f outstanding on %s invoices (%s unpaid, %s partial); unpaid older than 30 days: %s (Rs %.2f)'
          % (tot[0], tot[1], tot[2], tot[3], old[0], old[1]))
    print('\nBatches by status:', dict(q('SELECT status, COUNT(*) FROM batch GROUP BY 1')),
          '| published:', db.execute('SELECT COUNT(*) FROM batch WHERE published_on IS NOT NULL').fetchone()[0])
    print('Work orders by status:', dict(q('SELECT status, COUNT(*) FROM work_order GROUP BY 1')),
          '| open & overdue:', db.execute("SELECT COUNT(*) FROM work_order WHERE status='issued' AND due_on < ?", ('2026-11-22',)).fetchone()[0])
    print('Consignments:', q('SELECT cn_no, status FROM consignment'))
    print('\nRaw materials below reorder level:')
    for r in q('SELECT code,name,qty_on_hand,reorder_level,unit FROM v_raw_stock WHERE qty_on_hand < reorder_level'):
        print('  %s %-32s on hand %.2f %s < reorder %.2f' % (r[0], r[1], r[2], r[4], r[3]))
    print('\nMember balances (earned / paid / owed):')
    for r in q('SELECT m.code,m.name,b.earned,b.paid,b.balance FROM v_member_balance b JOIN member m ON m.id=b.member_id ORDER BY m.id'):
        print('  %s %-26s %10.2f %10.2f %10.2f' % r)
    print('\nAU alerts (valid_upto <= 2027-01-21):')
    for r in q('SELECT m.name,g.name,mg.au_valid_upto FROM member_gi mg JOIN member m ON m.id=mg.member_id JOIN gi g ON g.id=mg.gi_id WHERE mg.au_valid_upto<=? ORDER BY 3', ('2027-01-21',)):
        print('  %-24s %-28s %s' % r)
    print('\nGIs loaded: %d   without enrichment (generic checklist): %s' % (len(S.gis), S.unmatched or 'none'))
    skipped = [p[0] + '/' + p[1] for p in PRODUCTS if not S.gi_kw(p[0])]
    print('Products skipped (GI missing): %s' % (skipped or 'none'))
    for w in S.warnings:
        print('WARNING:', w)


def main():
    S = Seeder()
    S.seed_settings()
    S.seed_gi()
    S.seed_members()
    S.seed_materials_products()
    S.seed_customers()
    S.simulate()
    S.finalize()
    errs = run_checks(S.db)
    if errs:
        print('CONSISTENCY CHECKS FAILED (%d):' % len(errs))
        for e in errs[:40]:
            print('  -', e)
        sys.exit(1)
    print('Consistency checks: all passed')
    summary(S)


if __name__ == '__main__':
    main()
