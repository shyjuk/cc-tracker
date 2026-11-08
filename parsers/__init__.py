from parsers.emirates_islamic import EmiratesIslamicParser
from parsers.enbd import ENBDParser
from parsers.fab import FABParser
from parsers.cbd import CBDParser
from parsers.adcb import ADCBParser

PARSER_REGISTRY = {
    "emirates_islamic": EmiratesIslamicParser,
    "enbd": ENBDParser,
    "fab": FABParser,
    "cbd": CBDParser,
    "adcb": ADCBParser,
}

def get_parser(parser_name: str, pdf_stream):
    parser_cls = PARSER_REGISTRY.get(parser_name, EmiratesIslamicParser)
    return parser_cls(pdf_stream)
