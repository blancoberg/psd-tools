# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals, print_function
import warnings
import io
import zlib

from psd_tools.decoder import decoders
from psd_tools.decoder.actions import decode_descriptor, UnknownOSType
from psd_tools.decoder.color import decode_color
from psd_tools.exceptions import Error
from psd_tools.utils import read_fmt,read_unicode_string,read_pascal_string,read_be_array
from psd_tools.constants import EffectOSType, BlendMode , Compression
from psd_tools.debug import pretty_namedtuple
from psd_tools.reader.layers import ChannelData

from psd_tools.user_api.pil_support import get_icc_profile , _get_header_channel_ids , _channel_data_to_PIL
#from sys import getsizeof

#import packbits
#from pymaging.image import LoadedImage
#from pymaging.pixelarray import get_pixel_array
#from pymaging.colors import RGB, RGBA
#from user_api.pyimaging_support import _get_mode


_effect_info_decoders, register = decoders.new_registry()


Effects = pretty_namedtuple('Effects', 'version effects_count effects_list')
_LayerEffect = pretty_namedtuple('LayerEffect', 'effect_type effect_info')
ObjectBasedEffects = pretty_namedtuple('ObjectBasedEffects', 'version descriptor_version descriptor')

CommonStateInfo = pretty_namedtuple('CommonStateInfo', 'version visible unused')
ShadowInfo = pretty_namedtuple('ShadowInfo', 'version enabled '
                                             'blend_mode color opacity '
                                             'angle use_global_angle '
                                             'distance intensity blur '
                                             'native_color')
OuterGlowInfo = pretty_namedtuple('OuterGlowInfo', 'version enabled '
                                                   'blend_mode opacity color '
                                                   'intensity blur '
                                                   'native_color')
InnerGlowInfo = pretty_namedtuple('InnerGlowInfo', 'version enabled '
                                                   'blend_mode opacity color '
                                                   'intensity blur '
                                                   'invert native_color')
BevelInfo = pretty_namedtuple('BevelInfo', 'version enabled '
                                           'bevel_style '
                                           'depth direction blur '
                                           'angle use_global_angle '
                                           'highlight_blend_mode highlight_color highlight_opacity '
                                           'shadow_blend_mode shadow_color shadow_opacity '
                                           'real_highlight_color real_shadow_color')
SolidFillInfo = pretty_namedtuple('SolidFillInfo', 'version enabled '
                                                   'blend_mode color opacity '
                                                   'native_color')


class LayerEffect(_LayerEffect):

    def __repr__(self):
        return "LayerEffect(%s %s, %s)" % (self.effect_type, EffectOSType.name_of(self.effect_type),
                                           self.effect_info)

    def _repr_pretty_(self, p, cycle):
        # IS NOT TESTED!!
        if cycle:
            p.text('LayerEffect(...)')
        else:
            with p.group(1, 'LayerEffect(', ')'):
                p.breakable()
                p.text("%s %s," % (self.effect_type, EffectOSType.name_of(self.effect_type)))
                p.breakable()
                p.pretty(self.effect_info)

class Pattern:


    def __init__(self, name, id, data,w,h):
        self.name = name
        self.id = id
        self.data = data
        self.size = w , h

    def getImageData(self,root):

        print("root",_get_header_channel_ids(root.header))

        return _channel_data_to_PIL(
            channel_data=self.data,
            channel_ids=_get_header_channel_ids(root.header),
            color_mode=root.header.color_mode,
            size=self.size,
            depth=root.header.depth,
            icc_profile=get_icc_profile(root.decoded_data)
        )


        #return {}

def decode_virtual_memory_array_list(fp,w,h):

    start = fp.tell()
    version,length = read_fmt("II",fp)
    top,left,bottom,right,channels  = read_fmt("IIIIi",fp)

    print("topleftbottomright,channels",top,left,bottom,right,channels)
    ## virtal memory array list, repating x channels + user mask + sheet mask

    arrayWritten = read_fmt("I",fp)[0] # skip if 0
    ###############
    channel_data = []



    while arrayWritten != 0:


        length2 = read_fmt("I",fp)[0] # skip if 0
        dataStart = fp.tell()
        expectedEnding = dataStart + length2
        bytes_per_pixel = read_fmt("I",fp)[0] #  1, 8, 16 or 32
        anotherRect = fp.read(16)
        anotherDepth = fp.read(2)
        compress_type = fp.read(1)[0] # 1 = zip this is not correct in spec.

        #fp.seek(fp.tell())


        # read data size

        if compress_type == Compression.RAW:
            data_size = w * h * bytes_per_pixel
            #data = fp.read(data_size)
            data = fp.read(length2 - 23)

        elif compress_type == Compression.PACK_BITS:
            byte_counts = read_be_array("H", 200, fp) #channel_byte_counts[channel_id]
            data_size = sum(byte_counts)
            data = fp.read(data_size)

        #fix add more compression types
        channel_data.append(ChannelData(compress_type, data))
        print("decode virtual pixel depth at","expected pos",expectedEnding,"pos",fp.tell())


        arrayWritten = read_fmt("I",fp)[0]
    #########
    return channel_data


def decode_pattern(patternData):

    #print("decode pattern",somehint)
    # repeated for each pattern

    endOfPatterns = len(patternData)
    print ("end of pattern",endOfPatterns)

    fp = io.BytesIO(patternData)
    patterns = []

    #image mode Bitmap = 0; Grayscale = 1; Indexed = 2; RGB = 3; CMYK = 4; Multichannel = 7; Duotone = 8; Lab = 9
    patternLength = read_fmt("I",fp)[0]
    while patternLength!= 0:
        start = fp.tell()
        version,imageMode = read_fmt("II",fp)
        h,w = read_fmt("hh",fp)
        name = read_unicode_string(fp)
        unique_id = read_pascal_string(fp, 'ascii')
        print("decoding pattern",patternLength,version,imageMode,w,h,name,unique_id)
        data = decode_virtual_memory_array_list(fp,w,h)


        # seek to expected ending of pattern
        fp.seek(start + patternLength)
        
        if fp.tell() <= endOfPatterns-4:
            patternLength = read_fmt("I",fp)[0]
        else:
            patternLength = 0
        print ("pattern pos ",fp.tell(),"expected",start+patternLength,"end",endOfPatterns)

        patterns.append(Pattern(name, unique_id , data , w , h))

    #mode = _get_mode(len(data))

    return patterns



def decode(effects):
    """
    Reads and decodes info about layer effects.
    """
    fp = io.BytesIO(effects)

    version, effects_count = read_fmt("HH", fp)

    effects_list = []
    for idx in range(effects_count):
        sig = fp.read(4)
        if sig != b'8BIM':
            raise Error("Error parsing layer effect: invalid signature (%r)" % sig)

        effect_type = fp.read(4)
        if not EffectOSType.is_known(effect_type):
            warnings.warn("Unknown effect type (%s)" % effect_type)

        effect_info_length = read_fmt("I", fp)[0]
        effect_info = fp.read(effect_info_length)

        decoder = _effect_info_decoders.get(effect_type, lambda data: data)
        effects_list.append(LayerEffect(effect_type, decoder(effect_info)))

    return Effects(version, effects_count, effects_list)

def decode_object_based(effects):
    """
    Reads and decodes info about object-based layer effects.
    """
    fp = io.BytesIO(effects)

    version, descriptor_version = read_fmt("II", fp)
    try:
        descriptor = decode_descriptor(None, fp)
    except UnknownOSType as e:
        warnings.warn("Ignoring object-based layer effects tagged block (%s)" % e)
        return effects

    return ObjectBasedEffects(version, descriptor_version, descriptor)

def _read_blend_mode(fp):
    sig = fp.read(4)
    if sig != b'8BIM':
        raise Error("Error parsing layer effect: invalid signature (%r)" % sig)

    blend_mode = fp.read(4)
    if not BlendMode.is_known(blend_mode):
        warnings.warn("Unknown blend mode (%s)" % blend_mode)

    return blend_mode


@register(EffectOSType.COMMON_STATE)
def _decode_common_info(data):
    version, visible, unused = read_fmt("IBH", io.BytesIO(data))
    return CommonStateInfo(version, bool(visible), unused)


@register(EffectOSType.DROP_SHADOW)
@register(EffectOSType.INNER_SHADOW)
def _decode_shadow_info(data):
    fp = io.BytesIO(data)

    version, blur, intensity, angle, distance = read_fmt("IIIiI", fp)
    color = decode_color(fp)
    blend_mode = _read_blend_mode(fp)
    enabled, use_global_angle, opacity = read_fmt("3B", fp)

    native_color = None
    if version == 2:
        native_color = decode_color(fp)

    return ShadowInfo(
        version, bool(enabled),
        blend_mode, color, opacity,
        angle, bool(use_global_angle),
        distance, intensity, blur,
        native_color
    )


@register(EffectOSType.OUTER_GLOW)
def _decode_outer_glow_info(data):
    fp = io.BytesIO(data)

    version, blur, intensity = read_fmt("3I", fp)
    color = decode_color(fp)
    blend_mode = _read_blend_mode(fp)
    enabled, opacity = read_fmt("2B", fp)

    native_color = None
    if version == 2:
        native_color = decode_color(fp)

    return OuterGlowInfo(
        version, bool(enabled),
        blend_mode, opacity, color,
        intensity, blur,
        native_color
    )


@register(EffectOSType.INNER_GLOW)
def _decode_inner_glow_info(data):
    fp = io.BytesIO(data)

    version, blur, intensity = read_fmt("3I", fp)
    color = decode_color(fp)
    blend_mode = _read_blend_mode(fp)
    enabled, opacity = read_fmt("2B", fp)

    invert = None
    native_color = None
    if version == 2:
        invert = bool(read_fmt("B", fp)[0])
        native_color = decode_color(fp)

    return InnerGlowInfo(
        version, bool(enabled),
        blend_mode, opacity, color,
        intensity, blur,
        invert, native_color
    )


@register(EffectOSType.BEVEL)
def _decode_bevel_info(data):
    fp = io.BytesIO(data)

    version, angle, depth, blur = read_fmt("IiII", fp)

    highlight_blend_mode = _read_blend_mode(fp)
    shadow_blend_mode = _read_blend_mode(fp)

    highlight_color = decode_color(fp)
    shadow_color = decode_color(fp)

    bevel_style, highlight_opacity, shadow_opacity = read_fmt("3B", fp)
    enabled, use_global_angle, direction = read_fmt("3B", fp)

    real_highlight_color = None
    real_shadow_color = None
    if version == 2:
        real_highlight_color = decode_color(fp)
        real_shadow_color = decode_color(fp)

    return BevelInfo(
        version, bool(enabled),
        bevel_style,
        depth, direction, blur,
        angle, bool(use_global_angle),
        highlight_blend_mode, highlight_color, highlight_opacity,
        shadow_blend_mode, shadow_color, shadow_opacity,
        real_highlight_color, real_shadow_color
    )


@register(EffectOSType.SOLID_FILL)
def _decode_solid_fill_info(data):
    fp = io.BytesIO(data)

    version = read_fmt("I", fp)[0]
    blend_mode = _read_blend_mode(fp)
    color = decode_color(fp)
    opacity, enabled = read_fmt("2B", fp)

    native_color = decode_color(fp)

    return SolidFillInfo(
        version, bool(enabled),
        blend_mode, color, opacity,
        native_color
    )
