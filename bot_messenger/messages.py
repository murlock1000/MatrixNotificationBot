from enum import Enum
import os
import re

import magic

from nio import (
    AsyncClient,
)

class MessageType(Enum):
    BASE = 0
    TEXT = 1
    MEDIA = 2

class BaseMessage():
    message_type: MessageType = MessageType.BASE
    
    message_to: str
    recipient_user_id : str
    recipient_room_id : str
    
    message_type: MessageType
    message_length_in_bytes: int
    data: bytes
    
    is_valid : bool = True
    invalidation_reason : str
    
    def __init__(self, message_to:str, data:bytes, message_length_in_bytes:int):
        self.message_to = message_to
        self.recipient_room_id = None
        self.recipient_user_id = None
        self.data = data
        self.message_length_in_bytes = message_length_in_bytes
        
        self.validate_message_to()
        
    def validate_message_to(self):
        if self.message_to is None:
            self.invalidate_message(f"Recipient not provided, must be one of @user:server.com or !roomid:server.com in '-H \"Send-To: @user:server.com\"'" % self.message_to)
            return
        
        if re.match("@.*:.*", self.message_to):
            self.recipient_user_id = self.message_to
        elif re.match("!.*:.*", self.message_to):
            self.recipient_room_id = self.message_to
        else:
            self.invalidate_message(f"Invalid recipient: %s. Must be one of @user:server.com or !roomid:server.com" % self.message_to)
       
    def invalidate_message(self, reason:str):
        self.is_valid = False
        self.invalidation_reason = reason
        
    def __str__(self):
        if not self.is_valid:
            return self.invalidation_reason
        
        return f"Message_to : {self.message_to}, message_type: {self.message_type.name}, message_length: {self.message_length_in_bytes}"
    
    def get_content(self):
        
        if self.message_type == MessageType.TEXT:
            return self.data.decode('utf-8')
        
        if self.message_type == MessageType.MEDIA:
            return self.data
        
        return f"Message type {self.message_type} not implemented!"

class TextMessage(BaseMessage):   
    message_type: MessageType = MessageType.TEXT
    
    def __init__(self, message_to:str, data:bytes, message_length_in_bytes:int):
        super().__init__(message_to, data, message_length_in_bytes)
        self.validate_decodable_text()
        
    def validate_decodable_text(self):
        try:
            self.data.decode('utf-8')
        except Exception as e:
            self.invalidate_message(str(e))
    
    def get_content(self):
        return self.data.decode('utf-8')
    
    def __str__(self):
        if not self.is_valid:
            return self.invalidation_reason
        
        return f"{super().__str__()}, content: {self.get_content()}"
 
class MediaMessage(BaseMessage):
    message_type: MessageType = MessageType.MEDIA
    
    contentType: str
    file_name: str
    
    def __init__(self, message_to:str, data:bytes, message_length_in_bytes:int, content_type:str, file_name:str):
        super().__init__(message_to, data, message_length_in_bytes)
        self.contentType = content_type
        self.file_name = file_name
        self.validate_file_extension()
    
    def validate_file_extension(self):
        if self.file_name is None:
            self.invalidate_message(f"File name missing, add with '-H \"File-Name: filename.txt\"'")
            return
        
        extension = os.path.splitext(self.file_name)[1].lower()
        if extension == '':
            self.invalidate_message(f"File extension missing in {self.file_name}")
            return
        
        mime_type = magic.from_buffer(self.data, mime=True)
        if re.match("^.jpg$|^.jpeg$|^.gif$|^.png$|^.svg$", os.path.splitext(self.file_name)[1].lower()):
            if not mime_type.startswith("image/"):
                self.invalidate_message(
                    f"Image file {self.file_name} does not have an image mime type. "
                    "Should be something like image/jpeg. "
                    f"Found mime type {mime_type}. "
                    "This image is being dropped and NOT sent.")
        
    def get_content(self):
        return self.data
    
    def __str__(self):
        if not self.is_valid:
            return self.invalidation_reason

        return f"{super().__str__()}, file_name: {self.file_name}"