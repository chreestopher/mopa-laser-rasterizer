import numpy as np
from numpy import sin, cos, pi
from pprint import pprint
from dataclasses import dataclass
import PIL
import base64
import io

file_header = '''<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="1.2.01" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="True">
'''

file_footer = '''</LightBurnProject>
'''

class NotImplementedException(Exception):
    pass


class AffineTransform:
    def __init__(self,
                 A=np.array([[1., 0.], [0., 1.]], dtype=np.float64),
                 B=np.array((0, 0)), dtype=np.float64):
        self.A = np.array(A, dtype=np.float64)
        self.B = np.array(B, dtype=np.float64)

    def translate(self, x, y):
        self.B +=  np.array((x, y), dtype=np.float64)
        return self

    def rotate(self, anchor_x, anchor_y, angle):
        new = AffineTransform(self.A, self.B)
        rot_matrix = np.array([[cos(angle), sin(angle)],
                               [-sin(angle), cos(angle)]])
        new.A = np.matmul(rot_matrix, self.A)
        self.A = new.A
        anchor = np.array((anchor_x, anchor_y), dtype=np.float64)
        self.B = np.matmul(rot_matrix, self.B-anchor)+anchor
        return self

    def scale(self, sx, sy):
        self.A = np.matmul(self.A, [[sx, 0], [0, sy]])
        return self
    
    def write(self, f, offset):
        xform = np.append(self.A.reshape((4, 1)), self.B.reshape(2, 1))
        xform = " ".join([f"{x}" for x in xform])
        f.write(" "*offset + f'   <XForm>{xform}</XForm>\n')

    def __str__(self):
        return f"AffineTransform: {self.A}, {self.B}"

    def __repr__(self):
        return __str__(self)


shape_counter = 0
class Obj:
    def __init__(self):
        global shape_counter
        self.type = None
        self.transform = AffineTransform()
        self._layer = 0
        self._power=None
        self.shape_id = shape_counter
        shape_counter += 1

    def layer(self, layer):
        self._layer = layer
        return self

    def get_shape_id(self):
        return self.shape_id
    
    def write(self, f, offset):
        raise NotImplementedException(f"The writer for object {self.type} is not defined")

    def translate(self, x, y):
        self.transform.translate(x, y)
        return self

    def power(self, power):
        self._power = power
        return self

    def _power_scale_str(self):
        if self._power is None:
            return ""
        else:
            return f'PowerScale="{self._power}"'

    def rotate(self, anchor_x, anchor_y, angle_deg=None, angle_rad=None):
        if angle_deg is not None:
            angle_rad = angle_deg/360*2*pi
        self.transform.rotate(anchor_x, anchor_y, angle_rad)
        return self

    def scale(self, sx, sy):
        self.transform.scale(sx, sy)
        return self

    def shapeID(self, shape_id):
        self.shape_id = shape_id
        return self
    
class Text(Obj):
    def __init__(self, h, text, x=0, y=0, layer=None):
        super().__init__()
        self.type="text"
        self.height = h
        self.translate(x, y)
        self.text=text
        self.layer(layer)

    def __str__(self):
        return f"Text (L{self._layer}): height={self.height}, loc={self.transform}"

    def __repr__(self):
        return self.__str__()
    
    def write(self, f, offset):
        f.write(" "*offset + f'<Shape Type="Text" {self._power_scale_str()} ShapeID="{self.shape_id}" CutIndex="{self._layer}" Font="Arial,-1,100,5,50,0,0,0,0,0" Str="{self.text}" H="{self.height}" LS="0" LnS="0" Ah="0" Av="1" Weld="1" HasBackupPath="0">\n')
        self.transform.write(f, offset)
        f.write(" "*offset + f'</Shape>\n')

class Image(Obj):
    def __init__(self, w, h, image, x=0, y=0):
        """
        w, h = width, height
        image: a PIL (pillow) image
        """
        super().__init__()
        self.type="image"
        self.size = (w, h)
        self.translate(x, y)
        self.image = image
        self.mask_id = None

    def __str__(self):
        return f"Square (L{self._layer}): size={self.size}, loc={self.transform}"

    def __repr__(self):
        return self.__str__()
    
    def write(self, f, offset):
        f.write(" "*offset + f'<Shape Type="Bitmap" CutIndex="{self._layer}"\n')
        f.write(" "*offset + f'Gamma="1" ShapeID="{self.shape_id}" Contrast="0" Brightness="0" EnhanceAmount="0" EnhanceRadius="0" EnhanceDenoise="0"\n')
        if self.mask_id is not None:
            f.write(" "*offset + f'        MaskID="{self.mask_id}" \n')
        f.write(" "*offset + f'File="nofile" SourceHash="0" Data="{self.base64()}">')
        self.transform.write(f, offset)
        f.write(" "*offset + f'</Shape>\n')

    def base64(self):
        """ Return a base64 representation of self.image, as a PNG"""
        binary = io.BytesIO()
        self.image.save(binary, format="PNG")
        b64 = base64.b64encode(binary.getvalue())
        b64=b64.decode('UTF-8')
        return b64

    def maskID(self, mask_id):
        self.mask_id = mask_id
        return self

class Square(Obj):
    def __init__(self, w, h, x=0, y=0, layer=None, Cr=0):
        super().__init__()
        self.type="square"
        self.size = (w, h)
        self.Cr = Cr
        self.translate(x, y)
        
    def __str__(self):
        return f"Square (L{self._layer}): size={self.size}, loc={self.transform}"

    def __repr__(self):
        return self.__str__()

    def write(self, f, offset):
        f.write(" "*offset + f'<Shape Type="Rect" {self._power_scale_str()} ShapeID="{self.shape_id}" CutIndex="{self._layer}" W="{self.size[0]}" H="{self.size[1]}" Cr="{self.Cr}">\n')
        self.transform.write(f, offset)
        f.write(" "*offset + f'</Shape>\n')


class Ellipse(Obj):
    def __init__(self, Rx, Ry, x=0, y=0, layer=None):
        super().__init__()
        self.type="ellipse"
        self.size = (Rx, Ry)
        self.translate(x, y)
        
    def __str__(self):
        return f"Square (L{self._layer}): size={self.size}, loc={self.transform}"

    def __repr__(self):
        return self.__str__()

    def write(self, f, offset):
        f.write(" "*offset + f'<Shape Type="Ellipse" {self._power_scale_str()} ShapeID="{self.shape_id}" CutIndex="{self._layer}" Rx="{self.size[0]}" Ry="{self.size[1]}">\n')
        self.transform.write(f, offset)
        f.write(" "*offset + f'</Shape>\n')


class Path(Obj):
    def __init__(self, points = None, layer=None):
        super().__init__()
        self.type="path"
        if points is None:
            points = list()
        self.points = points
        
    def __str__(self):
        return f"Path (L{self._layer}): points={points_str}"

    def __repr__(self):
        return self.__str__()

    def write(self, f, offset):
        f.write(" "*offset + f'<Shape Type="Path" {self._power_scale_str()} ShapeID="{self.shape_id}" CutIndex="{self._layer}">\n')
        self.transform.write(f, offset)
        self._vertex_list_write(f, offset)
        f.write(" "*offset + "<PrimList>LineClosed</PrimList>\n")
        f.write(" "*offset + f'</Shape>\n')

    def _vertex_list_write(self, f, offset):
        f.write(" "*offset + '<VertList>\n')
        for point in self.points:
            x, y = point
            f.write(" "*offset + f'   V{x} {y}\n')
        f.write(" "*offset + '</VertList>\n')

@dataclass
class Layer:
    def __init__(self):
        self.type = None
        self.index = 0
        self.name = None
        self.minPower = 0
        self.maxPower = 100
        self.maxPower2 = 100
        self.speed = 100
        self.frequency = 100
        self.QPulseWidth = 200
        self.interval = .1
        self.angle = 0
        self.numPasses = 1
        self.anglePerPass = 0
        self.crossHatch = 0
        self.hide = 0
        self.dotTime = 1
        self.priority = 0
        self.tabCount = 1
        self.tabCountMax = 1
        

    def write(self, f):
        f.write(f'    <CutSetting type="{self.type}">\n'
                f'        <index Value="{self.index}"/>\n'
                f'        <name Value="{self.name}"/>\n'
                f'        <minPower Value="{self.minPower}"/>\n'
                f'        <maxPower Value="{self.maxPower}"/>\n'
                f'        <speed Value="{self.speed}"/>\n'
                f'        <frequency Value="{self.frequency}"/>\n'      # if self.frequency not None else None
                f'        <QPulseWidth Value="{self.QPulseWidth}"/>\n'  #if self.QPulseWidth not None else None
                f'        <hide Value="{int(self.hide)}"/>\n'
                f'        <dotTime Value="{self.dotTime}"/>\n'
                f'        <priority Value="{self.priority}"/>\n'
                f'        <tabCount Value="{self.tabCount}"/>\n'
                f'        <tabCountMax Value="{self.tabCountMax}"/>\n'
        )
        # These are Scan/Fill-only fields.  Omitting them from Line/Cut
        # layers prevents a material-library Scan setting, repurposed for a
        # line-only abstract effect, from becoming a mixed-mode project entry.
        if self.type == "Scan":
            f.write(f'        <maxPower2 Value="{self.maxPower2}"/>\n'
                    f'        <interval Value="{self.interval}"/>\n'
                    f'        <angle Value="{self.angle}"/>\n'
                    f'        <anglePerPass Value="{self.anglePerPass}"/>\n'
                    f'        <crossHatch Value="{int(self.crossHatch)}"/>\n')
        f.write(f'        <numPasses Value="{self.numPasses}"/>\n'
                f'    </CutSetting>\n')

class CutLayer(Layer):
    def __init__(self, index, name, minPower, maxPower, speed):
        super().__init__()
        self.type="Cut"
        self.index = index
        self.name = name
        self.minPower = minPower
        self.maxPower = maxPower
        self.speed = speed

        
class FillLayer(Layer):
    def __init__(self, index, name, minPower, maxPower, maxPower2=None, speed=3000, frequency=None, qPulseWidth=None, interval=None, angle=None, numPasses=1, crossHatch=False, anglePerPass=None, priority=None, hide=False) :
        super().__init__()
        self.type="Scan"
        self.index = index
        self.name = name
        self.minPower = minPower
        self.maxPower = maxPower
        self.maxPower2 = maxPower2
        self.speed = speed
        self.frequency = frequency if frequency is not None else 100
        self.QPulseWidth = qPulseWidth if qPulseWidth is not None else 200
        self.interval = interval if interval is not None else .1
        self.angle = angle if angle is not None else 0
        self.priority = priority if priority is not None else 0
        self.numPasses = numPasses if numPasses is not None else 1
        self.anglePerPass = anglePerPass if anglePerPass is not None else 0
        self.crossHatch = crossHatch
        self.hide = hide

class ImageLayer(Layer):
    def __init__(self, index, name, minPower, maxPower, speed, numPasses=1):
        super().__init__()
        self.type="Image"
        self.index = index
        self.name = name
        self.minPower = minPower
        self.maxPower = maxPower
        self.speed = speed
        self.numPasses=numPasses
        
    def write(self, f):
        f.write(f'    <CutSetting_Img type="Image">')
        f.write(f'        <index Value="{self.index}"/>\n')
        f.write(f'        <name Value="{self.index} pass"/>\n')
        f.write(f'        <minPower Value="{self.minPower}"/>\n')
        f.write(f'        <maxPower Value="{self.maxPower}"/>\n')
        f.write(f'        <speed Value="{self.speed}"/>\n')
        f.write(f'        <PPI Value="254"/>\n')
        f.write(f'        <numPasses Value="{self.numPasses}"/>\n')
        f.write(f'        <dotTime Value="1"/>\n')
        f.write(f'        <dotSpacing Value="0.01"/>\n')
        f.write(f'        <priority Value="0"/>\n')
        f.write(f'        <tabSize Value="0.1"/>\n')
        f.write(f'        <tabCount Value="1"/>\n')
        f.write(f'        <tabCountMax Value="1"/>\n')
        f.write(f'        <tabSpacing Value="1.1"/>\n')
        f.write(f'        <cellsPerInch Value="200"/>\n')
        f.write(f'        <negative Value="0"/>\n')
        f.write(f'        <ditherMode Value="grayscale"/>\n')
        f.write(f'    </CutSetting_Img>\n')

class Lightburn:
    def __init__(self):
        self.top = {
            "objects": list(),
            "children": list(),
            "parent": None
        }
        self.current = self.top
        self.objects = self.top["objects"]
        self._layers = list()

    def startgroup(self):
        self.current["children"].append(
            {
                "objects": list(),
                "children": list(),
                "parent": self.current
            })
        self.current = self.current["children"][-1]
        self.objects = self.current["objects"]
        
    def endgroup(self):
        self.current = self.current["parent"]
        self.objects = self.current["objects"]
        
    def add(self, obj: Obj):
        self.objects.append(obj)
        return self

    def reverse_layers(self):
        self._layers = self._layers[::-1]
        
    def reverse_objects(self):
        self.objects = self.objects[::-1]
        
    def add_layer(self, layer: Layer):
        self._layers.append(layer)

    def write(self, filename):
        with open(filename, "w") as f:
            f.write(file_header)
            self.write_cuts(f)
            self.write_objects(f)
            f.write(file_footer)
            print(f"Wrote {filename}.  You can load it directly into lightburn.", flush=True)

    def write_cuts(self, f):
        for layer in self._layers:
            layer.write(f)

    def write_object_list(self, obj_list, f):
        for obj in obj_list["objects"]:
            obj.write(f, self.offset)
        for child in obj_list["children"]:
            f.write(" "*self.offset + f'<Shape Type="Group">\n')
            self.offset += 4
            f.write(" "*self.offset + f'<XForm>1 0 0 1 0 0</XForm>\n')
            self.offset += 4
            f.write(" "*self.offset + f'<Children>\n')
            self.write_object_list(child, f)
            self.offset -= 4
            f.write(" "*self.offset + f'</Children>\n')
            self.offset -= 4
            f.write(" "*self.offset + f'</Shape>\n')
        
    def write_objects(self, f):
        self.offset=4
        self.write_object_list(self.top, f)

    def parse_material_library(self, filename):
        """ Parse a lightburn material library file, and return a list of layers"""
        from xml.etree import ElementTree as ET
        tree = ET.parse(filename)
        root = tree.getroot()
        layers = list()

        def parse_cut_setting(element):
            setting_type = element.attrib.get("type")
            if setting_type == "Cut":
                setting = CutLayer(0, None, 0, 100, 0)
            elif setting_type == "Scan":
                setting = FillLayer(0, None, 0, 100)
            elif setting_type == "Image":
                setting = ImageLayer(0, None, 0, 100, 0)
            else:
                setting = Layer()
                setting.type = setting_type

            setting.type = setting_type
            setting.linkPath = None
            setting.subLayers = []

            for child in element:
                value = child.attrib.get("Value")
                if child.tag == "index":
                    setting.index = int(value)
                elif child.tag == "name":
                    setting.name = value
                elif child.tag == "minPower":
                    setting.minPower = float(value)
                elif child.tag == "maxPower":
                    setting.maxPower = float(value)
                elif child.tag == "maxPower2":
                    setting.maxPower2 = float(value)
                elif child.tag == "speed":
                    setting.speed = float(value)
                elif child.tag == "frequency":
                    setting.frequency = int(value)
                elif child.tag == "QPulseWidth":
                    setting.QPulseWidth = float(value)
                elif child.tag == "interval":
                    setting.interval = float(value)
                elif child.tag == "angle":
                    setting.angle = float(value)
                elif child.tag == "numPasses":
                    setting.numPasses = int(value)
                elif child.tag == "anglePerPass":
                    setting.anglePerPass = float(value)
                elif child.tag == "crossHatch":
                    setting.crossHatch = bool(int(value))
                elif child.tag == "hide":
                    setting.hide = bool(int(value))
                elif child.tag == "priority":
                    setting.priority = int(value)
                elif child.tag == "tabCount":
                    setting.tabCount = int(value)
                elif child.tag == "tabCountMax":
                    setting.tabCountMax = int(value)
                elif child.tag == "LinkPath":
                    setting.linkPath = value
                elif child.tag == "PPI":
                    setting.PPI = float(value)
                elif child.tag == "dotTime":
                    setting.dotTime = float(value)
                elif child.tag == "dotSpacing":
                    setting.dotSpacing = float(value)
                elif child.tag == "ditherMode":
                    setting.ditherMode = value
                elif child.tag == "negative":
                    setting.negative = bool(int(value))
                elif child.tag == "autoRotate":
                    setting.autoRotate = bool(int(value))
                elif child.tag == "globalRepeat":
                    setting.globalRepeat = int(value)
                elif child.tag == "subname":
                    setting.subname = value
                elif child.tag == "cleanupPass":
                    setting.cleanupPass = int(value)
                elif child.tag == "scanOpt":
                    setting.scanOpt = value
                elif child.tag == "overscan":
                    setting.overscan = float(value)
                elif child.tag == "overscanPercent":
                    setting.overscanPercent = float(value)
                elif child.tag == "tabsEnabled":
                    setting.tabsEnabled = bool(int(value))
                elif child.tag == "tabSize":
                    setting.tabSize = float(value)
                elif child.tag == "tabSpacing":
                    setting.tabSpacing = float(value)
                elif child.tag == "SubLayer":
                    sub_layer = parse_cut_setting(child)
                    setting.subLayers.append(sub_layer)
                else:
                    setattr(setting, child.tag, value)

            return setting

        for material in root.findall("Material"):
            material_name = material.attrib.get("name")
            for entry in material.findall("Entry"):
                cutsetting = entry.find("CutSetting")
                if cutsetting is None:
                    continue
                setting = parse_cut_setting(cutsetting)
                setting.materialName = material_name
                setting.entryDesc = entry.attrib.get("Desc")
                setting.entryThickness = entry.attrib.get("Thickness")
                setting.entryNoThickTitle = entry.attrib.get("NoThickTitle")
                layers.append(setting)

        return layers

    def parse_material_settings(self, filename):
        return self.parse_material_library(filename)

def main():
    lb = Lightburn()
    for angle in np.linspace(0, 360*6, 100, endpoint=False):
        lb.add(Square(10, 10).translate(0, 0).rotate(10, 10, angle))
    lb.write("test.lbrn2")

if __name__ == "__main__":
    main()
