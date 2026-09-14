sequences = {
    "heat_trace_sequence": {
        "syntax_format": "{plant_name}-{HT_line}-{fluid_code}-{cnooc_sequence_number}-{circuit_identifier}-{cable_number}",
        "name": "HT Line Sequence"
    },
    "heat_trace_component_sequence": {
        "syntax_format": "{plant_name}-{HT_line}-{fluid_code}-{cnooc_sequence_number}-{circuit_identifier}-{electrical_component}",
        "name": "HT Equipment Sequence"
    },
    "instrument_tag_sequence": {
            "syntax_format": "{instrument_type}-{cnooc_sequence_number}",
            "name": "Instrument Tag"
        },
    "piping_line_no_insulation_sequence": {
        "syntax_format": "{line_size}-{fluid_code}-{cnooc_sequence_number}-{piping_line_class}",
        "name": "Piping Line without Insulation"
    },
    "piping_line_with_insulation_sequence": {
        "syntax_format": "{line_size}-{fluid_code}-{cnooc_sequence_number}-{piping_line_class}-{insulation_spec}",
        "name": "Piping Line with Insulation"
    },
    "piping_line_with_insulation_and_heat_trace_sequence": {
        "syntax_format": "{line_size}-{fluid_code}-{cnooc_sequence_number}-{piping_line_class}-{insulation_spec}-ET",
        "name": "Piping Line with Insulation and Heat Trace"
    },
    "valve_sequence": {
        "syntax_format": "{CNOOC_valve_sequence}",
        "name": "Valve Sequence"
    }
}

component_mapping = {
    "electrical_component_mapping": {
        "PWR Kit": "PWR",
        "Heat Trace PWR Kit": "PWR",
        "Heat Trace Splice Kit": "PWR",
        "RTD": "R",
        "name": "{electrical_component}"
    },
    "HT_mapping": {
        "name": "{HT_line}",
        "HT Line": "ET"
    }
}


line_size_mapping = {
    "1/2": "21mm",
    "3/4": "27mm",
    "1": "33mm",
    "1-1/4": "42mm",
    "1-1/2": "48mm",
    "2": "60mm",
    "2-1/2": "73mm",
    "3": "89mm",
    "4": "114mm",
    "5": "141mm",
    "6": "168mm",
    "8": "219mm",
    "10": "273mm",
    "12": "324mm",
    "name": "{line_size}"
}

fluid_code_mapping = {
    "A": "AMINE",
    "ADR": "AMINE DRAINS",
    "BD": "BLOWDOWN, BOILER",
    "BF": "BOILER FEED WATER",
    "BR": "WATER, SOURCE, BRACKISH",
    "CH": "CHEMICAL INJECTION",
    "CHD": "CLOSED HYDROCARBON DRAIN",
    "CML": "CORROSION MONITORING LOCATION",
    "CMR": "COOLING MEDIUM RETURN",
    "CMS": "COOLING MEDIUM SUPPLY",
    "CO": "COAGULANT",
    "DF": "DIESEL FUEL",
    "DR": "DRAINS (OPEN)",
    "DW": "WATER, DEMINERALIZED",
    "FG": "FUEL GAS",
    "FR": "FRESH SOURCE WATER",
    "FW": "FIRE WATER",
    "GL": "GLYCOL",
    "HA": "HYDROCHLORIC ACID",
    "HC": "HYDROCARBON CONDENSATE / DILUENT",
    "HMR": "HEAT MEDIUM (GLYCOL) RETURN",
    "HMS": "HEAT MEDIUM (GLYCOL) SUPPLY",
    "HPC": "HYPOCHLORITE",
    "IA": "INSTRUMENT AIR",
    "IW": "WATER, DISPOSAL",
    "K": "CAUSTIC",
    "LO": "LUBE OIL",
    "MFG": "MIXED FUEL GAS",
    "MT": "MECHANICAL EQUIPMENT TRIM",
    "N": "NITROGEN",
    "P": "MULTI-PHASE PRODUCTION STEAM",
    "PE": "PRODUCED EMULSION",
    "PG": "PRODUCED GAS",
    "PW": "WATER, PRODUCED",
    "RF": "RELIEF / FLARE",
    "RS": "RESIN SLURRY",
    "RW": "REGEN WASTE",
    "SAL": "SODA ASH SOLUTION",
    "SC": "STEAM CONDENSATE",
    "SD": "SAND SLURRY",
    "SG": "SOUR GAS",
    "SL": "LIME / MAGOX SLURRY",
    "SO": "SALES OIL (DILBIT PSC)",
    "SS": "SANITARY SEWER",
    "ST": "STEAM",
    "SYG": "SYNGAS",
    "UA": "UTILITY AIR",
    "UW": "WATER, UTILITY",
    "V": "VENT",
    "WA": "WATER, POTABLE",
    "WW": "WATER, WASTE",
    "name": "{fluid_code}"
}

sequence_number_mapping = {
    "sequence_number": r"^[A-Za-z]{1,2}\d{3,5}$",
    "name": "{sequence_number}",
    "keep_scovan": True
}

cable_number_mapping = {
    "cable_number": r"^\d{1,2}[A-Za-z]?(?:/\d{1,2}[A-Za-z]?)?$",
    "name": "{cable_number}",
    "keep_scovan": True
}

piping_line_class_mapping = {
    # Special compound mappings from Scovan piping spec {piping_category}{piping_material}{corrosion_allowance}{service_modifier}
    # to CNOOC Piping Line Class:
    "C1C4": "CAPC0",
    "C2C5": "CLPC0",
    "A2B1": "ALDB0",
    "C1C5": "CAPC0",
    "C1B4": "ALDB0",
    "name": "{piping_line_class}"
}

valve_mapping = {
    "21GA-C4-C5": "GA8410",
    "33GA-C4-C5": "GA8410",
    "33GA-C4-L8": "GA8610",
    "89GA-C1-C5": "GA6400",
    "89CH-C1-C5": "CH6400",
    "114CH-C1-C5": "CH6400",
    "114GA-C1-C5": "GA6400",
    "27GA-C4-C5": "GA8410",
    "27GA-C4-L8": "GA8610",
    "33GA-C3-L8": "GA8600",
    "33NE-C2-S50": "TBC",
    "33NE-C3-S50": "TBC",
    "27BR-A2-LA" :"TBC",
    "21BF-A2-LA": "BA6210F",
    "27GL-C4-C5": "GL8401",
    "168GA-C6-C5": "GA6521",
    "60GA-C1-L8": "GA6600",
    "60CH-C1-C5": "CH6400",
    "60GA-C1-C5": "GA6400",
    "33CH-C3-L5": "CH8620",
    "33BR-A2-LA": "BA6210",
    "33GA-A2-L8": "TBC",
    "33GL-C3-C5": "TBC",
    "name": "{CNOOC_valve_sequence}"
}
