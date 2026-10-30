"""City → country for T20 league venues (host country of a match). Unknown cities return None."""
from __future__ import annotations

_COUNTRY = {
    "Pakistan": ["Lahore", "Karachi", "Rawalpindi", "Multan", "Peshawar", "Faisalabad", "Islamabad", "Quetta",
                 "Hyderabad (Sind)"],
    "United Arab Emirates": ["Dubai", "Sharjah", "Abu Dhabi"],
    "India": ["Mumbai", "Navi Mumbai", "Chennai", "Kolkata", "Delhi", "New Delhi", "Bengaluru", "Bangalore", "Hyderabad",
              "Ahmedabad", "Jaipur", "Mohali", "Chandigarh", "Pune", "Lucknow", "Dharamsala", "Visakhapatnam",
              "Guwahati", "Indore", "Raipur", "Ranchi", "Cuttack", "Nagpur", "Rajkot", "Kanpur", "Kochi",
              "Thiruvananthapuram", "Mullanpur", "New Chandigarh"],
    "Australia": ["Sydney", "Melbourne", "Adelaide", "Perth", "Brisbane", "Hobart", "Canberra", "Geelong",
                  "Launceston", "Gold Coast", "Carrara", "Coffs Harbour", "Albury", "Cairns", "Townsville",
                  "Darwin", "Mackay"],
    "South Africa": ["Johannesburg", "Cape Town", "Durban", "Centurion", "Port Elizabeth", "Gqeberha", "Paarl",
                     "East London", "Bloemfontein", "Kimberley", "Potchefstroom", "Benoni", "Pietermaritzburg"],
    "England": ["London", "Birmingham", "Manchester", "Leeds", "Southampton", "Nottingham", "Cardiff", "Bristol",
                "Chester-le-Street", "Taunton", "Hove", "Chelmsford", "Leicester", "Derby", "Northampton",
                "Worcester", "Canterbury", "Scarborough", "Uxbridge", "Beckenham", "Arundel"],
    "West Indies": ["Bridgetown", "Port of Spain", "Tarouba", "Kingston", "Providence", "Basseterre", "Gros Islet",
                    "St Lucia", "North Sound", "Lauderhill", "Warner Park"],
    "Bangladesh": ["Dhaka", "Mirpur", "Chattogram", "Chittagong", "Sylhet", "Khulna", "Fatullah", "Rajshahi"],
    "Sri Lanka": ["Colombo", "Kandy", "Pallekele", "Galle", "Hambantota", "Dambulla"],
    "New Zealand": ["Auckland", "Wellington", "Christchurch", "Hamilton", "Mount Maunganui", "Napier", "Dunedin",
                    "Nelson", "Queenstown", "Whangarei", "Tauranga"],
    "United States of America": ["Grand Prairie", "Dallas", "Morrisville", "New York", "Lauderhill",
                                 "Fort Lauderdale", "Oakland", "Houston"],
    "Zimbabwe": ["Harare", "Bulawayo"],
    "Afghanistan": ["Kabul"],
    "Canada": ["King City", "Brampton", "Toronto"],
    "Nepal": ["Kirtipur", "Kathmandu"],
}

_LOOKUP = {city.lower(): country for country, cities in _COUNTRY.items() for city in cities}
SHORT = {"United Arab Emirates": "UAE", "United States of America": "USA"}


def same_country(a, b) -> bool:
    """"United Arab Emirates" and "UAE" (and "USA") are the same country; case and spacing don't matter."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    norm = lambda c: SHORT.get(c.strip(), c.strip()).lower()   # noqa: E731
    return norm(a) == norm(b)


def city_country(name) -> str | None:
    """Country for a city (or a venue name containing a known city), short form for UAE/USA."""
    if not isinstance(name, str) or not name.strip():
        return None
    s = name.strip().lower()
    if s in _LOOKUP:
        c = _LOOKUP[s]
        return SHORT.get(c, c)
    for city, c in _LOOKUP.items():
        if f" {city}" in f" {s}" and len(city) > 3:
            return SHORT.get(c, c)
    return None
