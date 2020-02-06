import logging
import os


def fhir_version_name(fhir_version):
    """
    Get the name of a particular FHIR version number

    :param: fhir_version
    :type: str

    :returns: str
    """
    major_version = int(fhir_version.split('.')[0])

    if major_version < 3:
        return 'dstu2'
    elif (major_version >= 3) and (major_version < 4):
        return 'stu3'
    elif (major_version >= 4) and (major_version < 5):
        return 'r4'
    else:
        raise Exception(
            f'Invalid fhir version supplied: {fhir_version}! No name exists '
            'for the supplied fhir version.'
        )


DEFAULT_LOG_LEVEL = logging.DEBUG

FHIR_VERSION = '4.0.0'
FHIR_VERSION_NAME = fhir_version_name(FHIR_VERSION)
CONFORMANCE_RESOURCES = {
    'CapabilityStatement',
    'StructureDefinition',
    'CodeSystem',
    'ValueSet',
    'ImplementationGuide',
    'SearchParameter',
    'MessageDefinition',
    'OperationDefinition',
    'CompartmentDefinition',
    'StructureMap',
    'GraphDefinition',
    'ExampleScenario'
}

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
