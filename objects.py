# TODO:
#   what is "DYNPROPS: True"?
#   where do descriptions come from?
#   how to determine start of TOC in class instance?
# BUGs:
#   class instance: "root\\CIMV2" Microsoft_BDD_Info NS_68577372C66A7B20658487FBD959AA154EF54B5F935DCC5663E9228B44322805/CI_6FCB95E1CB11D0950DA7AE40A94D774F02DCD34701D9645E00AB9444DBCF640B/IL_EEC4121F2A07B61ABA16414812AA9AFC39AB0A136360A5ACE2240DC19B0464EB.1606.116085.3740

import logging
from datetime import datetime
from collections import namedtuple

from funcy.objects import cached_property

from common import h
from common import one
from common import LoggingObject
from cim import Key
from cim import Index
import vstruct
from vstruct.primitives import *

logging.basicConfig(level=logging.DEBUG)
g_logger = logging.getLogger("cim.objects")


ROOT_NAMESPACE_NAME = "root"
SYSTEM_NAMESPACE_NAME = "__SystemClass"
NAMESPACE_CLASS_NAME = "__namespace"


class FILETIME(vstruct.primitives.v_prim):
    _vs_builder = True
    def __init__(self):
        vstruct.primitives.v_prim.__init__(self)
        self._vs_length = 8
        self._vs_value = "\x00" * 8
        self._vs_fmt = "<Q"
        self._ts = datetime.min

    def vsParse(self, fbytes, offset=0):
        offend = offset + self._vs_length
        q = struct.unpack("<Q", fbytes[offset:offend])[0]
        self._ts = datetime.utcfromtimestamp(float(q) * 1e-7 - 11644473600 )
        return offend

    def vsEmit(self):
        raise NotImplementedError()

    def vsSetValue(self, guidstr):
        raise NotImplementedError()

    def vsGetValue(self):
        return self._ts

    def __repr__(self):
        return self._ts.isoformat("T") + "Z"


class WMIString(vstruct.VStruct):
    def __init__(self):
        vstruct.VStruct.__init__(self)
        self.zero = v_uint8()
        self.s = v_zstr()

    def __repr__(self):
        return repr(self.s)

    def vsGetValue(self):
        return self.s.vsGetValue()


class ClassDefinitionHeader(vstruct.VStruct):
    def __init__(self):
        vstruct.VStruct.__init__(self)
        self.super_class_unicode_length = v_uint32()
        self.super_class_unicode = v_wstr(size=0)  # not present if no superclass
        self.timestamp = FILETIME()
        self.unk0 = v_uint8()
        self.unk1 = v_uint32()
        self.offset_class_name = v_uint32()
        self.junk_length = v_uint32()

        # junk type:
        #   0x19 - has 0xC5000000 at after about 0x10 bytes of 0xFF
        #     into `junk`
        self.unk3 = v_uint32()
        self.super_class_ascii = WMIString()  # not present if no superclass

        # has to do with junk
        # if junk type:
        #   0x19 - then 0x11
        #   0x18 - then 0x10
        #   0x17 - then 0x0F
        self.unk4 = v_uint32()  # not present if no superclass

    def pcb_super_class_unicode_length(self):
        self["super_class_unicode"].vsSetLength(self.super_class_unicode_length * 2)
        if self.super_class_unicode_length == 0:
            self.vsSetField("super_class_ascii", v_str(size=0))
            self.vsSetField("unk4", v_str(size=0))


CIM_TYPES = v_enum()
CIM_TYPES.CIM_TYPE_LANGID = 0x3
CIM_TYPES.CIM_TYPE_REAL32 = 0x4
CIM_TYPES.CIM_TYPE_STRING = 0x8
CIM_TYPES.CIM_TYPE_BOOLEAN = 0xB
CIM_TYPES.CIM_TYPE_UINT8 = 0x11
CIM_TYPES.CIM_TYPE_UINT16 = 0x12
CIM_TYPES.CIM_TYPE_UINT32= 0x13
CIM_TYPES.CIM_TYPE_UINT64 = 0x15
CIM_TYPES.CIM_TYPE_DATETIME = 0x65

CIM_TYPE_SIZES = {
    CIM_TYPES.CIM_TYPE_LANGID: 4,
    CIM_TYPES.CIM_TYPE_REAL32: 4,
    CIM_TYPES.CIM_TYPE_STRING: 4,
    CIM_TYPES.CIM_TYPE_BOOLEAN: 2,
    CIM_TYPES.CIM_TYPE_UINT8: 1,
    CIM_TYPES.CIM_TYPE_UINT16: 2,
    CIM_TYPES.CIM_TYPE_UINT32: 4,
    CIM_TYPES.CIM_TYPE_UINT64: 8,
    # looks like: stringref to "\x00 00000000000030.000000:000"
    CIM_TYPES.CIM_TYPE_DATETIME: 4
}


class BaseType(object):
    """
    this acts like a CimType, but its not backed by some bytes,
      and is used to represent a type.
    probably not often used. good example is an array CimType
      that needs to pass along info on the type of each item.
      each item is not an array, but has the type of the array.
    needs to adhere to CimType interface.
    """
    def __init__(self, type_, value_parser):
        self._type = type_
        self._value_parser = value_parser

    def getType(self):
        return self._type

    def isArray(self):
        return False

    @property
    def value_parser(self):
        return self._value_parser

    def __repr__(self):
        return CIM_TYPES.vsReverseMapping(self._type)

    @property
    def base_type_clone(self):
        return self


class CimType(vstruct.VStruct):
    def __init__(self):
        vstruct.VStruct.__init__(self)
        self.type = v_uint8()
        self._is_array = v_uint8()
        self.unk0 = v_uint8()
        self.unk2 = v_uint8()

    @property
    def is_array(self):
        return self._is_array == 0x20

    @property
    def value_parser(self):
        if self.is_array:
            return v_uint32
        elif self.type == CIM_TYPES.CIM_TYPE_LANGID:
            return v_uint32
        elif self.type == CIM_TYPES.CIM_TYPE_REAL32:
            return v_float
        elif self.type == CIM_TYPES.CIM_TYPE_STRING:
            return v_uint32
        elif self.type == CIM_TYPES.CIM_TYPE_BOOLEAN:
            return v_uint16
        elif self.type == CIM_TYPES.CIM_TYPE_UINT8:
            return v_uint8
        elif self.type == CIM_TYPES.CIM_TYPE_UINT16:
            return v_uint16
        elif self.type == CIM_TYPES.CIM_TYPE_UINT32:
            return v_uint32
        elif self.type == CIM_TYPES.CIM_TYPE_UINT64:
            return v_uint64
        elif self.type == CIM_TYPES.CIM_TYPE_DATETIME:
            return v_uint32
        else:
            raise RuntimeError("unknown qualifier type: %s", h(self.type))

    def __repr__(self):
        r = ""
        if self.is_array:
            r += "arrayref to "
        r += CIM_TYPES.vsReverseMapping(self.type)
        return r

    @property
    def base_type_clone(self):
        return BaseType(self.type, self.value_parser)


BUILTIN_QUALIFIERS = v_enum()
BUILTIN_QUALIFIERS.PROP_KEY = 0x1
BUILTIN_QUALIFIERS.PROP_READ_ACCESS = 0x3
BUILTIN_QUALIFIERS.CLASS_NAMESPACE = 0x6
BUILTIN_QUALIFIERS.CLASS_UNK = 0x7
BUILTIN_QUALIFIERS.PROP_TYPE = 0xA


class QualifierReference(vstruct.VStruct):
    # ref:4 + unk0:1 + valueType:4 = 9
    MIN_SIZE = 9

    def __init__(self):
        vstruct.VStruct.__init__(self)
        self.key_reference = v_uint32()
        self.unk0 = v_uint8()
        self.value_type = CimType()
        self.value = v_bytes(size=0)

    def pcb_value_type(self):
        P = self.value_type.value_parser
        self.vsSetField("value", P())

    @property
    def is_builtin_key(self):
        return self.key_reference & 0x80000000 > 0

    @property
    def key(self):
        return self.key_reference & 0x7FFFFFFF

    def __repr__(self):
        return "QualifierReference(type: {:s}, isBuiltinKey: {:b}, keyref: {:s})".format(
                self.value_type,
                self.is_builtin_key,
                h(self.key)
            )


class QualifiersList(vstruct.VStruct):
    def __init__(self):
        vstruct.VStruct.__init__(self)
        self.count = 0
        self.size = v_uint32()
        self.qualifiers = vstruct.VArray()

    def vsParse(self, bytez, offset=0, fast=False):
        soffset = offset
        offset = self["size"].vsParse(bytez, offset=offset)
        eoffset = soffset + self.size

        self.count = 0
        while offset + QualifierReference.MIN_SIZE <= eoffset:
            q = QualifierReference()
            offset = q.vsParse(bytez, offset=offset)
            self.qualifiers.vsAddElement(q)
            self.count += 1
        return offset

    def vsParseFd(self, fd):
        # TODO
        raise NotImplementedError()


class _Property(vstruct.VStruct):
    def __init__(self):
        vstruct.VStruct.__init__(self)
        self.type = CimType()  # the on-disk type for this property's value
        self.entry_number = v_uint16()  # the on-disk order for this property
        self.unk1 = v_uint32()
        self.unk2 = v_uint32()
        self.qualifiers = QualifiersList()


class Property(LoggingObject):
    def __init__(self, class_def, propref):
        super(Property, self).__init__()
        self._class_definition = class_def
        self._propref = propref

        # this is the raw struct, without references/strings resolved
        self._prop = _Property()
        property_offset = self._propref.offset_property_struct
        self._prop.vsParse(self._class_definition.data, offset=property_offset)

    def __repr__(self):
        return "Property(name: {:s}, type: {:s}, qualifiers: {:s})".format(
            self.name,
            CIM_TYPES.vsReverseMapping(self.type.getType),
            ",".join("%s=%s" % (k, str(v)) for k, v in self.qualifiers.iteritems()))

    @property
    def name(self):
        return self._class_definition.get_string(self._propref.offset_property_name)

    @property
    def type(self):
        return self._prop.type

    @property
    def qualifiers(self):
        """ get dict of str to str """
        ret = {}
        for i in xrange(self._prop.qualifiers.count):
            q = self._prop.qualifiers.qualifiers[i]
            qk = self._class_definition.get_qualifier_key(q)
            qv = self._class_definition.get_qualifier_value(q)
            ret[str(qk)] = str(qv)
        return ret

    @property
    def entry_number(self):
        return self._prop.entry_number


class PropertyReference(vstruct.VStruct):
    def __init__(self):
        vstruct.VStruct.__init__(self)
        self.offset_property_name = v_uint32()
        self.offset_property_struct = v_uint32()


class PropertyReferenceList(vstruct.VStruct):
    def __init__(self):
        vstruct.VStruct.__init__(self)
        self.count = v_uint32()
        self.refs = vstruct.VArray()

    def pcb_count(self):
        self.refs.vsAddElements(self.count, PropertyReference)


class ClassDefinition(vstruct.VStruct, LoggingObject):
    def __init__(self):
        vstruct.VStruct.__init__(self)
        LoggingObject.__init__(self)

        self.header = ClassDefinitionHeader()
        self.qualifiers_list = QualifiersList()
        self.property_references = PropertyReferenceList()
        self.junk = v_bytes(size=0)
        self._data_length = v_uint32()
        self.data = v_bytes(size=0)

    def pcb_header(self):
        self["junk"].vsSetLength(self.header.junk_length)

    @property
    def data_length(self):
        return self._data_length & 0x7FFFFFFF

    def pcb__data_length(self):
        self["data"].vsSetLength(self.data_length)

    def __repr__(self):
        return "ClassDefinition(name: {:s})".format(self.class_name)

    def get_string(self, ref):
        s = WMIString()
        s.vsParse(self.data, offset=int(ref))
        return str(s.s)

    def get_array(self, ref, item_type):
        Parser = item_type.value_parser
        data = self.data

        arraySize = v_uint32()
        arraySize.vsParse(data, offset=int(ref))

        items = []
        offset = ref + 4  # sizeof(array_size:uint32_t)
        for i in xrange(arraySize):
            p = Parser()
            p.vsParse(data, offset=offset)
            items.append(self.get_value(p, item_type))
            offset += len(p)
        return items

    def get_value(self, value, value_type):
        """
        value: is a parsed value, might need dereferencing
        value_type: is a CimType
        """
        if value_type.is_array:
            return self.get_array(value, value_type.base_type_clone)

        t = value_type.type
        if t == CIM_TYPES.CIM_TYPE_STRING:
            return self.get_string(value)
        elif t == CIM_TYPES.CIM_TYPE_BOOLEAN:
            return value != 0
        elif CIM_TYPES.vsReverseMapping(t):
            return value
        else:
            raise RuntimeError("unknown qualifier type: %s", str(value_type))

    def get_qualifier_value(self, qualifier):
        return self.get_value(qualifier.value, qualifier.value_type)

    def get_qualifier_key(self, qualifier):
        if qualifier.is_builtin_key:
            return BUILTIN_QUALIFIERS.vsReverseMapping(qualifier.key)
        return self.get_string(qualifier.key)

    @property
    def class_name(self):
        """ return string """
        return self.get_string(self.header.offset_class_name)

    @property
    def super_class_name(self):
        """ return string """
        return str(self.header.super_class_unicode)

    @property
    def timestamp(self):
        """ return datetime.datetime """
        return self.header.timestamp

    @cached_property
    def qualifiers(self):
        """ get dict of str to str """
        ret = {}
        for i in xrange(self.qualifiers_list.count):
            q = self.qualifiers_list.qualifiers[i]
            qk = self.get_qualifier_key(q)
            qv = self.get_qualifier_value(q)
            ret[str(qk)] = str(qv)
        return ret

    @cached_property
    def properties(self):
        """ get dict of str to Property instances """
        ret = {}
        for i in xrange(self.property_references.count):
            propref = self.property_references.refs[i]
            prop = Property(self, propref)
            ret[prop.name] = prop
        return ret


class ClassInstance(vstruct.VStruct, LoggingObject):
    def __init__(self, class_layout):
        vstruct.VStruct.__init__(self)
        LoggingObject.__init__(self)

        self.class_layout = class_layout
        self._buf = None

        self.vsParse(self._buf)

        self.name_hash = v_wstr(size=0x40)
        self.ts1 = FILETIME()
        self.ts2 = FILETIME()
        self.data_length = v_uint32()
        self.extra_padding = v_bytes(size=0)

        self.toc = vstruct.VArray()
        for prop in self.class_layout.properties:
            self.toc.vsAddElement(prop.type.value_parser())

        self.qualifiers_list = QualifiersList()
        self.unk1 = v_uint8()
        self.property_data_length = v_uint32()  # high bit always set
        self.property_data = v_bytes(size=0)

        self._property_index_map = {prop.name: i for i, prop in enumerate(self.class_layout.properties)}
        self._property_type_map = {prop.name: prop.type for prop in self.class_layout.properties}

    def set_buffer(self, buf):
        """
        This is a hack until we can correctly compute extra_padding_length without trial and error.
        Must be called before vsParse.
        """
        self._buf = buf

    def pcb_data_length(self):
        # hack: at this point, we know set_buffer must have been called
        self["extra_padding"].vsSetLength(self.extra_padding_length())

    def pcb_property_data_length(self):
        self["property_data"].vsSetLength(self.property_data_length & 0x7FFFFFFF)

    def pcb_unk1(self):
        if self.unk1 != 0x1:
            # seems that when this field is 0x0, then there is additional property data
            # maybe this is DYNPROPS: True???
            raise NotImplementedError("ClassInstance.unk1 != 0x1: %s" % h(self.unk1))

    def __repr__(self):
        # TODO: make this nice
        return "ClassInstance(classhash: {:s})".format(self._def.nameHash)

    def extra_padding_length(self):
        class_definition = self.class_layout.class_definition
        if class_definition.header.unk3 == 0x18:
            return class_definition.header.unk1 + 0x6

        # these are all the same, split up to be explicit
        elif class_definition.header.unk3 == 0x19:
            return class_definition.header.unk1 + 0x5
        elif class_definition.header.unk3 == 0x17:
            # do math. its a hack.
            # try both 0x5 and 0x6 + CD.header.unk0, then seek
            #  to find the qualifiers length and data length, and
            #  see if they match the data size.
            s = v_uint32()

            toc_length = 0
            for prop in self.class_layout.properties:
                if prop.type.is_array:
                    toc_length += 0x4
                else:
                    toc_length += CIM_TYPE_SIZES[prop.type.type]

            u1 = class_definition.header.unk1
            for i in [5, 6]:
                possible_toc_end = 0x94 + u1 + i + toc_length
                s.vsParse(self._buf, possible_toc_end)
                o = int(s)
                qualifiers_length = o
                if o > len(self._buf):
                    continue
                o = possible_toc_end + qualifiers_length + 1
                s.vsParse(self._buf, o)
                p = int(s) & 0x7FFFFFFF
                if possible_toc_end + qualifiers_length + 5 + p != len(self._buf):
                    continue
                return u1 + i
            raise RuntimeError("Unable to determine extraPadding len")
        else:
            return class_definition.header.unk1 + 0x5

    def get_string(self, ref):
        s = WMIString()
        s.vsParse(self.property_data, offset=int(ref))
        return str(s.s)

    def get_array(self, ref, item_type):
        if ref == 0:
            # seems a little fragile. can't have array as first element?
            # empirically, the first element is the item type name, fortunately
            return []

        Parser = item_type.value_parser
        data = self.property_data

        arraySize = v_uint32()
        arraySize.vsParse(data, offset=int(ref))

        items = []
        offset = ref + 4  # sizeof(array_size:uint32_t)
        for i in xrange(arraySize):
            p = Parser()
            p.vsParse(data, offset=offset)
            items.append(self.get_value(p, item_type))
            offset += len(p)
        return items

    def get_value(self, value, value_type):
        """
        value is a parsed value, might need dereferencing
        valueType is a CimType
        """
        if value_type.is_array:
            return self.get_array(value, value_type.base_type_clone)

        t = value_type.type
        if t == CIM_TYPES.CIM_TYPE_STRING:
            return self.get_string(value)
        elif t == CIM_TYPES.CIM_TYPE_DATETIME:
            # TODO: perhaps this should return a parsed datetime?
            return self.get_string(value)
        elif t == CIM_TYPES.CIM_TYPE_BOOLEAN:
            return value != 0
        elif CIM_TYPES.vsReverseMapping(t):
            return value
        else:
            raise RuntimeError("unknown qualifier type: %s",
                    str(value_type))

    def get_qualifier_value(self, qualifier):
        return self.get_value(qualifier.value, qualifier.value_type)

    def get_qualifier_key(self, qualifier):
        if qualifier.is_builtin_key:
            return BUILTIN_QUALIFIERS.vsReverseMapping(qualifier.key)
        return self.get_string(qualifier.key)

    @property
    def class_name(self):
        return self.get_string(0x0)

    @cached_property
    def qualifiers(self):
        """ get dict of str to str """
        ret = {}
        for i in xrange(self.qualifiers_list.count):
            q = self.qualifiers_list.qualifiers[i]
            qk = self.get_qualifier_key(q)
            qv = self.get_qualifier_value(q)
            ret[str(qk)] = str(qv)
        return ret

    @cached_property
    def properties(self):
        """ get dict of str to Property instances """
        ret = []
        for prop in self.class_layout.properties:
            n = prop.name
            i = self._property_index_map[n]
            t = self._property_type_map[n]
            v = self.toc[i]
            ret.append(self.get_value(v, t))
        return ret

    def get_property_value(self, name):
        i = self._property_index_map[name]
        t = self._property_type_map[name]
        v = self.toc[i]
        return self.get_value(v, t)

    def get_property(self, name):
        raise NotImplementedError()


class ClassLayout(LoggingObject):
    def __init__(self, object_resolver, namespace, class_definition):
        super(ClassLayout, self).__init__()
        self.object_resolver = object_resolver
        self.namespace = namespace
        self.class_definition = class_definition

    @property
    def properties(self):
        class_name = self.class_definition.class_name
        class_derivation = []  # initially, ordered from child to parent
        while class_name != "":
            cd = self.object_resolver.get_cd(self.namespace, class_name)
            class_derivation.append(cd)
            self.d("parent of %s is %s", class_name, cd.super_class_name)
            class_name = cd.super_class_name

        # note, derivation now ordered from parent to child
        class_derivation.reverse()

        self.d("%s derivation: %s",
                self.class_definition.class_name,
                map(lambda c: c.class_name, class_derivation))

        ret = []
        while len(class_derivation) > 0:
            cd = class_derivation.pop(0)
            for prop in sorted(cd.properties.values(), key=lambda p: p.entry_number):
                ret.append(prop)

        self.d("%s property layout: %s",
                self.class_definition.class_name,
                map(lambda p: p.name, ret))
        return ret

    @property
    def instance(self):
        return ClassInstance(self)

    @cached_property
    def properties_toc_length(self):
        off = 0
        for prop in self.properties:
            if prop.type.is_array:
                off += 0x4
            else:
                off += CIM_TYPE_SIZES[prop.type.type]
        return off


class ObjectResolver(LoggingObject):
    def __init__(self, cim, index):
        super(ObjectResolver, self).__init__()
        self._cim = cim
        self._index = index
        self._cdcache = {}
        self._clcache = {}

    def _build(self, prefix, name=None):
        if name is None:
            return prefix
        else:
            return prefix + self._index.hash(name.upper().encode("UTF-16LE"))

    def NS(self, name=None):
        return self._build("NS_", name)

    def CD(self, name=None):
        return self._build("CD_", name)

    def CR(self, name=None):
        return self._build("CR_", name)

    def R(self, name=None):
        return self._build("R_", name)

    def CI(self, name=None):
        return self._build("CI_", name)

    def KI(self, name=None):
        return self._build("KI_", name)

    def IL(self, name=None):
        return self._build("IL_", name)

    def I(self, name=None):
        return self._build("I_", name)

    def get_object(self, query):
        """ fetch the first object buffer matching the query """
        ref = one(self._index.lookup_keys(query))
        # TODO: should ensure this query has a unique result
        return self._cim.logical_data_store.get_object_buffer(ref)

    def get_objects(self, query):
        """ return a generator of object buffers matching the query """
        refs = self._index.lookup_keys(query)
        for ref in refs:
            yield self._cim.logical_data_store.get_object_buffer(ref)

    @property
    def root_namespace(self):
        return SYSTEM_NAMESPACE_NAME

    def get_cd_buf(self, namespace_name, class_name):
        q = Key("{}/{}".format(
                self.NS(namespace_name),
                self.CD(class_name)))
        # TODO: should ensure this query has a unique result
        ref = one(self._index.lookup_keys(q))

        # some standard class definitions (like __NAMESPACE) are not in the
        #   current NS, but in the __SystemClass NS. So we try that one, too.

        if ref is None:
            self.d("didn't find %s in %s, retrying in %s", class_name, namespace_name, SYSTEM_NAMESPACE_NAME)
            q = Key("{}/{}".format(
                    self.NS(SYSTEM_NAMESPACE_NAME),
                    self.CD(class_name)))
        return self.get_object(q)

    def get_cd(self, namespace_name, class_name):
        c_id = get_class_id(namespace_name, class_name)
        c_cd = self._cdcache.get(c_id, None)
        if c_cd is None:
            self.d("cdcache miss")

            q = Key("{}/{}".format(
                    self.NS(namespace_name),
                    self.CD(class_name)))
            # TODO: should ensure this query has a unique result
            ref = one(self._index.lookup_keys(q))

            # some standard class definitions (like __NAMESPACE) are not in the
            #   current NS, but in the __SystemClass NS. So we try that one, too.

            if ref is None:
                self.d("didn't find %s in %s, retrying in %s", class_name, namespace_name, SYSTEM_NAMESPACE_NAME)
                q = Key("{}/{}".format(
                        self.NS(SYSTEM_NAMESPACE_NAME),
                        self.CD(class_name)))
            c_cdbuf = self.get_object(q)
            c_cd = ClassDefinition()
            c_cd.vsParse(c_cdbuf)
            self._cdcache[c_id] = c_cd
        return c_cd

    def get_cl(self, namespace_name, class_name):
        c_id = get_class_id(namespace_name, class_name)
        c_cl = self._clcache.get(c_id, None)
        if not c_cl:
            self.d("clcache miss")
            c_cd = self.get_cd(namespace_name, class_name)
            c_cl = ClassLayout(self, namespace_name, c_cd)
            self._clcache[c_id] = c_cl
        return c_cl

    def get_ci(self, namespace_name, class_name, instance_name):
        pass

    @property
    def ns_cd(self):
        return self.get_cd(SYSTEM_NAMESPACE_NAME, NAMESPACE_CLASS_NAME)

    @property
    def ns_cl(self):
        return self.get_cl(SYSTEM_NAMESPACE_NAME, NAMESPACE_CLASS_NAME)

    NamespaceSpecifier = namedtuple("NamespaceSpecifier", ["namespace_name"])
    def get_ns_children_ns(self, namespace_name):
        q = Key("{}/{}/{}".format(
                    self.NS(namespace_name),
                    self.CI(NAMESPACE_CLASS_NAME),
                    self.IL()))

        for ns_i in self.get_objects(q):
            i = self.ns_cl.instance
            # hack: until we can compute extra_padding_length
            i.set_buffer(ns_i)
            i.vsParse(ns_i)
            yield self.NamespaceSpecifier(namespace_name + "\\" + i.get_property_value("Name"))

    ClassDefinitionSpecifier = namedtuple("ClassDefintionSpecifier", ["namespace_name", "class_name"])
    def get_ns_children_cd(self, namespace_name):
        q = Key("{}/{}".format(
                    self.NS(namespace_name),
                    self.CD()))

        for cdbuf in self.get_objects(q):
            cd = ClassDefinition()
            cd.vsParse(cdbuf)
            yield self.ClassDefinitionSpecifier(namespace_name, cd.class_name)

    ClassInstanceSpecifier = namedtuple("ClassInstanceSpecifier", ["namespace_name", "class_name", "instance_name"])
    def get_cd_children_ci(self, namespace_name, class_name):
        # CI or KI?
        q = Key("{}/{}/{}".format(
                    self.NS(namespace_name),
                    self.CI(class_name),
                    self.IL()))

        # HACK: TODO: fixme, use getObjects(q) instead
        for ref in self._index.lookup_keys(q):
            ibuf = self.get_object(ref)
            instance = self.get_cl(namespace_name, class_name).instance.vsParse(ibuf)
            # TODO: need to parse key here, don't assume its "Name"
            yield self.ClassInstanceSpecifier(namespace_name, class_name, instance.get_property_value("Name"))


def get_class_id(namespace, classname):
    return namespace + ":" + classname


class TreeNamespace(LoggingObject):
    def __init__(self, object_resolver, name):
        super(TreeNamespace, self).__init__()
        self._object_resolver = object_resolver
        self.name = name

    def __repr__(self):
        return "Namespace(name: {:s})".format(self.name)

    @property
    def namespace(self):
        """ get parent namespace """
        if self.name == ROOT_NAMESPACE_NAME:
            return None
        else:
            # TODO
            raise NotImplementedError()

    @property
    def namespaces(self):
        """ return a generator direct child namespaces """
        for ns in self._object_resolver.get_ns_children_ns(self.name):
            yield TreeNamespace(self._object_resolver, ns.namespace_name)

    @property
    def classes(self):
        for cd in self._object_resolver.get_ns_children_cd(self.name):
            yield TreeClassDefinition(self._object_resolver, self.name, cd.class_name)


class TreeClassDefinition(LoggingObject):
    def __init__(self, object_resolver, namespace, name):
        super(TreeClassDefinition, self).__init__()
        self._object_resolver = object_resolver
        self.ns = namespace
        self.name = name

    def __repr__(self):
        return "ClassDefinition(namespace: {:s}, name: {:s})".format(self.ns, self.name)

    @property
    def namespace(self):
        """ get parent namespace """
        return TreeNamespace(self._object_resolver, self.ns)

    @property
    def cd(self):
        return self._object_resolver.get_cd(self.ns, self.name)

    @property
    def cl(self):
        return self._object_resolver.get_cl(self.ns, self.name)

    @property
    def instances(self):
        """ get instances of this class definition """
        for ci in self._object_resolver.get_cd_children_cis(self.ns, self.name):
            yield TreeClassInstance(self._object_resolver, self.name, ci.class_name, ci.instance_name)


class TreeClassInstance(LoggingObject):
    def __init__(self, object_resolver, namespace_name, class_name, instance_name):
        super(TreeClassInstance, self).__init__()
        self._object_resolver = object_resolver
        self.ns = namespace_name
        self.class_name = class_name
        self.instance_name = instance_name

    def __repr__(self):
        return "ClassInstance(namespace: {:s}, class: {:s}, name: {:s})".format(
            self.ns,
            self.class_name,
            self.instance_name)

    @property
    def klass(self):
        """ get class definition """
        return TreeClassDefinition(self._object_resolver, self.ns, self.class_name)

    @property
    def namespace(self):
        """ get parent namespace """
        return TreeNamespace(self._object_resolver, self.ns)


class Tree(LoggingObject):
    def __init__(self, cim):
        super(Tree, self).__init__()
        self._object_resolver = ObjectResolver(cim, Index(cim.getCimType, cim.logical_index_store))

    def __repr__(self):
        return "Tree"

    @property
    def root(self):
        """ get root namespace """
        return TreeNamespace(self._object_resolver, ROOT_NAMESPACE_NAME)
