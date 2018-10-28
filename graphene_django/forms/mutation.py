# from django import forms
from collections import OrderedDict

import graphene
from graphene import Field, InputField
from graphene.relay.mutation import ClientIDMutation
from graphene.types.mutation import MutationOptions

# from graphene.types.inputobjecttype import (
#     InputObjectTypeOptions,
#     InputObjectType,
# )
from graphene.types.utils import yank_fields_from_attrs
from graphene_django.registry import get_global_registry

from ..utils import create_errors_type
from .converter import convert_form_field
from .types import ErrorType


def fields_for_form(form, only_fields, exclude_fields):
    fields = OrderedDict()
    for name, field in form.fields.items():
        is_not_in_only = only_fields and name not in only_fields
        is_excluded = (
            name
            in exclude_fields  # or
            # name in already_created_fields
        )

        if is_not_in_only or is_excluded:
            continue

        fields[name] = convert_form_field(field)
    return fields


class BaseDjangoFormMutation(ClientIDMutation):
    class Meta:
        abstract = True

    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        form = cls.get_form(root, info, **input)

        if form.is_valid():
            return cls.perform_mutate(form, info)
        else:
            # TODO: double check non field errors name
            errors = cls.Errors(**form.errors)

            return cls(errors=errors)

    @classmethod
    def get_form(cls, root, info, **input):
        form_kwargs = cls.get_form_kwargs(root, info, **input)
        return cls._meta.form_class(**form_kwargs)

    @classmethod
    def get_form_kwargs(cls, root, info, **input):
        kwargs = {"data": input}

        pk = input.pop("id", None)
        if pk:
            instance = cls._meta.model._default_manager.get(pk=pk)
            kwargs["instance"] = instance

        return kwargs


# class DjangoFormInputObjectTypeOptions(InputObjectTypeOptions):
#     form_class = None


# class DjangoFormInputObjectType(InputObjectType):
#     class Meta:
#         abstract = True

#     @classmethod
#     def __init_subclass_with_meta__(cls, form_class=None,
#                                     only_fields=(), exclude_fields=(), _meta=None, **options):
#         if not _meta:
#             _meta = DjangoFormInputObjectTypeOptions(cls)
#         assert isinstance(form_class, forms.Form), (
#             'form_class must be an instance of django.forms.Form'
#         )
#         _meta.form_class = form_class
#         form = form_class()
#         fields = fields_for_form(form, only_fields, exclude_fields)
#         super(DjangoFormInputObjectType, cls).__init_subclass_with_meta__(_meta=_meta, fields=fields, **options)


class DjangoFormMutationOptions(MutationOptions):
    form_class = None
    model = None
    return_field_name = None

class DjangoFormMutation(BaseDjangoFormMutation):
    class Meta:
        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        form_class=None,
        return_field_name=None,
        only_fields=(),
        exclude_fields=(),
        **options
    ):

        if not form_class:
            raise Exception("form_class is required for DjangoFormMutation")

        form = form_class()
        input_fields = fields_for_form(form, only_fields, exclude_fields)
        input_fields = yank_fields_from_attrs(input_fields, _as=InputField)

        base_name = cls.__name__

        _meta = DjangoFormMutationOptions(cls)

        cls.Errors = create_errors_type(
            "{}Errors".format(base_name),
            input_fields
        )

        output_fields = OrderedDict()

        if hasattr(form, '_meta') and hasattr(form._meta, 'model'):
            model = form._meta.model
            _meta.model = model

            registry = get_global_registry()
            model_type = registry.get_type_for_model(model)
            return_field_name = return_field_name

            if "id" not in exclude_fields:
                input_fields["id"] = graphene.ID()

            if not return_field_name:
                model_name = model.__name__

                return_field_name = model_name[:1].lower() + model_name[1:]

            # TODO: model_type might be none

            output_fields[return_field_name] = graphene.Field(model_type)
        else:
            form_name = form.__class__.__name__

            if not return_field_name:
                return_field_name = form_name[:1].lower() + form_name[1:]

            # TODO: registry

            form_fields = fields_for_form(
                form, only_fields, exclude_fields
            )

            form_type = type(
                form_name,
                (graphene.ObjectType, ),
                yank_fields_from_attrs(form_fields, _as=graphene.Field),
            )

            output_fields[return_field_name] = graphene.Field(form_type)

        output_fields['errors'] = graphene.Field(cls.Errors, required=True)

        _meta.return_field_name = return_field_name
        _meta.form_class = form_class
        _meta.fields = yank_fields_from_attrs(output_fields, _as=Field)

        super(DjangoFormMutation, cls).__init_subclass_with_meta__(
            _meta=_meta, input_fields=input_fields, **options
        )

    @classmethod
    def perform_mutate(cls, form, info):
        obj = form.save()
        kwargs = {cls._meta.return_field_name: obj}
        return cls(errors={}, **kwargs)