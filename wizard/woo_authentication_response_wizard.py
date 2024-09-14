# -*- coding: utf-8 -*-

from odoo.exceptions import UserError
from odoo import models, api, _, fields


class WooAuthenticationResponseWizard(models.Model):
    _name = 'woo.authentication.response.wizard'
    _description = 'Woo Authentication Response Wizard'

    authentication_response = fields.Text('Authentication Response', readonly=True)
