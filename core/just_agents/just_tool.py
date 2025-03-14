from typing import Callable, Optional, List, Dict, Any, Sequence, Union, Literal, TypeVar

from litellm.utils import function_to_dict
from pydantic import BaseModel, Field, PrivateAttr
from just_agents.just_bus import JustEventBus, VariArgs, SubscriberCallback
from importlib import import_module
import inspect
from pydantic import ConfigDict
import sys

FunctionParamFields=Literal["kind","default","type_annotation"]
FunctionParams = List[Dict[str, Dict[FunctionParamFields,Optional[str]]]]

# Create a TypeVar for the class
if sys.version_info >= (3, 11):
    from typing import Self
else:
    Self = TypeVar('Self', bound='JustTool')

class JustToolsBus(JustEventBus):
    """
    A simple singleton tools bus.
    Inherits from JustEventBus with no additional changes.
    """
    pass


class LiteLLMDescription(BaseModel):

    model_config = ConfigDict(populate_by_name=True)
    
    name: Optional[str] = Field(..., alias='function', description="The name of the function")
    description: Optional[str] = Field(None, description="The docstring of the function.")
    parameters: Optional[Dict[str,Any]]= Field(None, description="Parameters of the function.")

class JustTool(LiteLLMDescription):
    package: str = Field(..., description="The name of the module where the function is located.")
    auto_refresh: bool = Field(True, description="Whether to automatically refresh the tool after initialization.")
    arguments: Optional[FunctionParams] = Field(
         None, description="List of parameters with their details.", exclude=True
    )
    _callable: Optional[Callable] = PrivateAttr(default=None)

    def model_post_init(self, __context):
        """Called after the model is initialized. Refreshes the tools metainfo if auto_refresh is True."""
        super().model_post_init(__context)
        if self.auto_refresh:
            self.refresh()

    @staticmethod
    def _wrap_function(func: Callable, name: str) -> Callable:
        """
        Helper to wrap a function with event publishing logic to JustToolsBus.
        """
        def __wrapper(*args, **kwargs):
            bus = JustToolsBus()
            bus.publish(f"{name}.execute", *args, kwargs=kwargs)
            try:
                result = func(*args, **kwargs)
                bus.publish(f"{name}.result", result_interceptor=result, kwargs=kwargs)
                return result
            except Exception as e:
                bus.publish(f"{name}.error", error=e)
                raise e
        return __wrapper


    @staticmethod
    def _extract_parameters(func: Callable) -> List[Dict[str, Any]]:
        """Extract parameters from the function's signature."""
        signature = inspect.signature(func)
        parameters = []
        for name, param in signature.parameters.items():
            param_info = {
                'kind': str(param.kind),
                'default': str(param.default) if param.default != param.empty else None,
                'type_annotation': str(param.annotation) if param.annotation != param.empty else None
            }
            parameters.append({ name: param_info})
        return parameters

    def get_litellm_description(self) -> Dict[str, Any]:
        dump = self.model_dump(
            mode='json',
            by_alias=False,
            exclude_none=True,
            serialize_as_any=False,
            include=set(super().model_fields)
        )
        return dump


    @classmethod
    def from_callable(cls, input_function: Callable) -> Self:
        """Create a JustTool instance from a callable."""
        package = input_function.__module__
        litellm_description = function_to_dict(input_function)
        arguments = cls._extract_parameters(input_function)
        
        # Get function name either from litellm description or directly from the function
        function_name = litellm_description.get('function') or input_function.__name__
        
        wrapped_callable = cls._wrap_function(input_function, function_name)
        
        # Ensure function name is in litellm_description
        if 'function' not in litellm_description:
            litellm_description['function'] = function_name

        return cls(
            **litellm_description,
            package=package,
            arguments=arguments,
            _callable=wrapped_callable,
        )

    def subscribe(self, callback: SubscriberCallback, type: Optional[str]=None) -> bool:
        """
        Subscribe to the JustToolsBus.
        """
        bus = JustToolsBus()
        if type is None:
            return bus.subscribe(f"{self.name}.*", callback)
        else:
            return bus.subscribe(f"{self.name}.{type}", callback)

    def unsubscribe(self, callback: SubscriberCallback,type: Optional[str]=None) -> bool:
        """
        Unsubscribe from the JustToolsBus.
        """
        bus = JustToolsBus()
        if type is None:
            return bus.unsubscribe(f"{self.name}.*", callback)
        else:
            return bus.unsubscribe(f"{self.name}.{type}", callback)

    def subscribe_to_call(self, callback: SubscriberCallback) -> None:
        """
        Subscribe to the call event.
        
        Args:
            callback (SubscriberCallback): Callback function that takes event_name (str) and *args, kwargs=kwargs
        """
        if not self.subscribe(callback, "execute"):
            raise ValueError(f"Failed to subscribe to {self.name}.execute")

    def subscribe_to_result(self, callback: SubscriberCallback) -> None:
        """
        Subscribe to the result event.
        
        Args:
            callback (SubscriberCallback): Callback function that takes event_name (str) and result_interceptor=result
        """
        if not self.subscribe(callback, "result"):
            raise ValueError(f"Failed to subscribe to {self.name}.result")

    def subscribe_to_error(self, callback: SubscriberCallback) -> None:
        """
        Subscribe to the error event.
        """
        if not self.subscribe(callback, "error"):
            raise ValueError(f"Failed to subscribe to {self.name}.error")

    def refresh(self)->Self:
        """
        Refresh the JustTool instance to reflect the current state of the actual function.
        Updates package, function name, description, parameters, and ensures the function is importable.
        Returns:
            JustTool: Returns self to allow method chaining or direct appending.
        """
        try:
            # Get the function from the module
            func = getattr(import_module(self.package), self.name)
            # Update LiteLLM description
            litellm_description = LiteLLMDescription (**function_to_dict(func))
            # Update the description
            self.description = litellm_description.description
            # Update parameters
            self.parameters= litellm_description.parameters
            self.arguments = self._extract_parameters(func)
            # Rewrap with the updated callable
            self._callable = self._wrap_function(func, self.name)

            return self
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Error refreshing {self.name} from {self.package}: {e}") from e

    def get_callable(self, refresh: bool = False) -> Callable:
        """
        Retrieve the callable function.
        If refresh is True, the callable is refreshed before returning.
        """
        if refresh:
            self.refresh()
        if self._callable is not None:
            return self._callable
        try:
            func = getattr(import_module(self.package), self.name)
            self._callable = self._wrap_function(func, self.name)
            return self._callable
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Error importing {self.name} from {self.package}: {e}")

    def __call__(self, *args, **kwargs):
        """Allows the JustTool instance to be called like a function."""
        func = self.get_callable()
        return func(*args, **kwargs)

JustTools = Union[
    Dict[str, JustTool],  # A dictionary where keys are strings and values are JustTool instances.
    Sequence[
        Union[JustTool, Callable]
    ]  # A sequence (like a list or tuple) containing either JustTool instances or callable objects (functions).
]
