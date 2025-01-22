from enum import Enum
from typing import List, Union, Optional
from pydantic import HttpUrl, Field, BaseModel, ConfigDict, AliasPath, field_validator
from pydantic_core import from_json

""" Common OpenAI data structures conventions """

# Content types and enums
class Role(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"

    # make it similar to Literal["system", "user", "assistant", tool] while retaining enum convenience
    def __new__(cls, value, *args, **kwargs):
        obj = str.__new__(cls, value)
        obj._value_ = value
        return obj

    def __str__(self): #handles use_enum_values==False cases in str context without .value
        return str(self.value)

class TextContent(BaseModel):
    type: str = Field("text", examples=["text"])
    text: str = Field(..., examples=["What are in these images? Is there any difference between them?"])

class ImageContent(BaseModel):
    type: str = Field("image_url", examples=["image_url"])
    image_url: HttpUrl = Field(..., examples=["https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg"])

# Message class - Simple string content or a list of text or image content for vision model
class Message(BaseModel):
    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
    )
    role: Optional[Role] = Field(..., examples=[Role.assistant], description="The role of the author of this message.")
    content: Optional[Union[
        str,  # Simple string content
        List[Union[TextContent, ImageContent]]
    ]] = Field(
        ...,
        description="Content can be a simple string, or a list of content items including text or image URLs."
    )

    def get_text(self, delimiter: str = " ", preserve_trailing: bool = False) -> str:
        """
        Retrieves text from the content, optionally joining list items with a custom delimiter.

        Args:
            delimiter (str): The string used to join list items. Defaults to a space.
            preserve_trailing (bool): If True, adds a trailing delimiter at the end. Defaults to False.

        Returns:
            str: The concatenated text or the content string.
        """
        content = self.content
        if isinstance(content, list):
            # Filter for TextContent items
            text_items = [item.text for item in content if isinstance(item, TextContent)]
            # Join with the delimiter and optionally add a trailing one
            joined_text = delimiter.join(text_items)
            return joined_text + delimiter if preserve_trailing and text_items else joined_text
        elif isinstance(content, str):
            return content
        return ""

    def text_format(self, delimiter: str = " ", preserve_trailing: bool = False) -> 'Message':
        message = self.model_copy(deep=True)
        message.content = self.get_text(delimiter, preserve_trailing)
        return message

# Tool call class
class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(..., description="The ID of the tool call.")
    index: Optional[int] = Field(None)
    name: str = Field(
        ...,
        validation_alias=AliasPath('function', 'name'),
        description="The name of the function to call.")
    arguments: Union[str, dict] = Field(
        ...,
        validation_alias=AliasPath('function', 'arguments'),
        description="""
        The arguments to call the function with, as generated by the model in JSON
        format. Note that the model does not always generate valid JSON, and may
        hallucinate parameters not defined by your function schema. Validate the
        arguments in your code before calling your function.
        """
    )
    type: Optional[str] = Field('function', description="The type of the tool. Currently, only `function` is supported.")

    @field_validator('arguments', mode='before')
    @classmethod
    def parse_arguments(cls, value):
        try:
            parsed = from_json(value, allow_partial=True)
            return parsed
        except ValueError as e:
            return str(e)