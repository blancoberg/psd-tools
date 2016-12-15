

import re

nodeStack = []
propertyStack = []
currentNode = []
currentLine = 0
textLines = []

"""
    engineData is raw data from psd-tools parser
"""

def paresr(engineData):

    global nodeStack
    global propertyStack
    global currentNode
    global textLines

    # reset
    nodeStack = []
    propertyStack = []
    currentNode = []

    # save raw textlines globally so it
    # can be accessed when parsing utf-16 strings

    textLines = textSegment(engineData)
    textReg(textLines)

    return currentNode.pop(0)

def textSegment(text):
    return text.split(b'\n');

def textReg(textArr):

    global currentLine

    def matchText(currentText):
        currentText = binaryToString(currentText)
        typeMatch(currentText)

    for i in range(len(textArr)):
        currentLine = i
        matchText(textArr[i])


def typeMatch(currentText):

    global MATCH_TYPE

    for currentType in range(len(MATCH_TYPE)):

        t = MATCH_TYPE[currentType](currentText)
        if t["match"] != None:
            return t["parse"]()

    return currentText

# helper functinos


# convert binarystring to string
# removes tabs from the beginning of string

def binaryToString(txt):
    textAsString = str(txt)[2:-1]
    return re.sub(r'\\t', '', textAsString,flags=re.DOTALL)


def Match(reg, text, settings = None):

    if(settings):
        result = re.match(reg,text ,settings)
    else:
        result = re.match(reg,text )
    return result


def isArray(o):
    return type(o) is list

def hashStart(text):

    reg = r'^<<$'
    def parse():
        stackPush({})

    return {
        "match": Match(reg, text),
        "parse": parse
    }

def hashEnd(text):

    reg = r'^>>$'
    def parse():
        updateNode()

    return {
        "match": Match(reg, text),
        "parse": parse
    }


def multiLineArrayStart(text):

    reg = r'^\/(\w+) \[$'

    def parse():
        propertyStack.append(  re.match(reg,text).group(1))
        stackPush([])

    return {
        "match": Match(reg, text),
        "parse": parse
    }


def multiLineArrayEnd(text):

    reg = r'^\]$'

    def parse():
        updateNode()

    return {
        "match": Match(reg, text),
        "parse": parse
    }

def property(text):

    reg = r'^/([A-Z0-9]+)$'

    def parse():
        value = re.match(reg,text,flags = re.IGNORECASE).group(1)
        propertyStack.append(value)

    return {
        "match": Match(reg, text,re.IGNORECASE),
        "parse": parse
    }

def propertyWithData(text):

    reg = r'^/([A-Z0-9]+)\s((.|\r)*)$'

    def parse():

        match = re.match(reg,text,flags = re.IGNORECASE)

        pushKeyValue(match.group(1), typeMatch(match.group(2)))

    return {
        "match": Match(reg, text,re.IGNORECASE),
        "parse": parse
    }


def boolean(text):

    reg = r'^(true|false)$'

    def parse():

        if text == "true":
            return True
        else:
            return False

    return {
        "match": Match(reg, text),
        "parse": parse
    }

def number(text):

    reg = r'^-?\d+$'

    def parse():
        return int(text)

    return {
        "match": Match(reg, text),
        "parse": parse
    }


def numberWithDecimal(text):

    reg = r'^(-?\d*)\.(\d+)$'

    def parse():
        return float(text)

    return {
        "match": Match(reg, text),
        "parse": parse
    }

def singleLineArray(text):

    #单行数组似乎只有数字数组的情况
    reg = r'^\[(.*)\]$'

    def parse():

        items = re.match(reg,text).group(1).strip().split(' ')
        tempArr = []

        for i in range(len(items)):
            tempArr.append(typeMatch(items[i]))

        return tempArr

    return {
        "match": Match(reg, text),
        "parse": parse
    }

# I got tired of trying the get the regular python decoding function to work
# so this will have to do for the moment :) Probably works in most cases.

def decodeUTF16Dirty(text):

    #skip bom
    i = 2
    decodedText = "";

    #skip every other character ( null values )
    while i<len(text)-1:
        decodedText=decodedText+chr(text[i+1])
        i=i+2

    return decodedText



def string(text):

    global textLines
    global currentLine
    reg = r'^\(((.|\r)*)\)$'

    def parse():

        # get raw data
        textLine = textLines[currentLine]

        textInsideParanthesis = re.search(b'\(([^()]+)\)',textLine,flags=re.DOTALL)
        #print("paranthesis",textInsideParanthesis.group(1))
        #decodedText = decodeUTF16Dirty(textInsideParanthesis.group(0))
        decodedText = textInsideParanthesis.group(1).decode("utf-16")
        return decodedText


    return {
        "match": Match(reg, text),
        "parse": parse
    }


# node handle

def stackPush(node):

    global nodeStack
    global currentNode
    nodeStack.append(currentNode)
    currentNode = node

def updateNode():

    global nodeStack
    global currentNode
    global propertyStack

    node = nodeStack.pop()
    if isArray(node):
        node.append(currentNode)
    else:
        node[propertyStack.pop()] = currentNode

    currentNode = node

def pushKeyValue(key,value):

    global currentNode
    currentNode[key] = value


MATCH_TYPE = [

    hashStart,
    hashEnd,
    multiLineArrayStart,
    multiLineArrayEnd,
    property,
    propertyWithData,
    singleLineArray,
    boolean,
    number,
    numberWithDecimal,
    string
]
