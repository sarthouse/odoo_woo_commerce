# -*- coding: utf-8 -*-
import imghdr
import urllib
import base64
import requests
import json
import itertools
import logging
import time
from woocommerce import API
from urllib.request import urlopen
from odoo.exceptions import UserError
from odoo import models, api, fields, _
from odoo.tools import config
from bs4 import BeautifulSoup
config['limit_time_real'] = 1000000


_logger = logging.getLogger(__name__)


class WooProductImage(models.Model):
    _name = 'woo.product.image'
    _description = 'woo.product.image'

    name = fields.Char()
    product_id = fields.Many2one('product.product', ondelete='cascade')
    template_id = fields.Many2one(
        'product.template', string='Product template', ondelete='cascade')
    image = fields.Image()
    url = fields.Char(string="Image URL", help="External URL of image")

    @api.onchange('url')
    def validate_img_url(self):
        if self.url:
            try:
                image_types = ["image/jpeg", "image/png", "image/tiff", "image/vnd.microsoft.icon", "image/x-icon",
                               "image/vnd.djvu", "image/svg+xml", "image/gif"]
                response = urllib.request.urlretrieve(self.url)

                if response[1].get_content_type() not in image_types:
                    raise UserError(
                        _("Please provide valid Image URL with any extension."))
                else:
                    photo = base64.encodebytes(urlopen(self.url).read())
                    self.image = photo

            except Exception as error:
                raise UserError(_("Invalid Url"))


class ProductProduct(models.Model):
    _inherit = 'product.product'

    woo_id = fields.Char('WooCommerce ID')
    woo_regular_price = fields.Float('WooCommerce Regular Price')
    # DB woo_product_weight = fields.Float("Woo Weight")
    # woo_product_length = fields.Float("Woo Length")
    # woo_product_width = fields.Float("Woo Width")
    # woo_product_height = fields.Float("Woo Height")
    # woo_weight_unit = fields.Char(compute='_compute_weight_uom_name')
    # woo_unit_other = fields.Char(compute='_compute_length_uom_name')
    is_exported = fields.Boolean('Sincronizado con Woocommerce', default=False)
    woo_instance_id = fields.Many2one('woo.instance', ondelete='cascade')
    woo_varient_description = fields.Text('Woo Variant Description')
    default_code = fields.Char(
        'Internal Reference', index=True, required=False)
    woo_sale_price = fields.Float('WooCommerce Sales Price')
    wps_subtitle = fields.Char(string="Woo wps subtitle")

    def cron_export_product(self):
        all_instances = self.env['woo.instance'].sudo().search([])
        for rec in all_instances:
            if rec:
                self.env['product.product'].export_selected_product_variant(rec)

    def export_selected_product_variant(self, instance_id):
        location = instance_id.url
        cons_key = instance_id.client_id
        sec_key = instance_id.client_secret
        version = 'wc/v3'

        wcapi = API(url=location, consumer_key=cons_key,
                    consumer_secret=sec_key, version=version)

        selected_ids = self.env.context.get('active_ids', [])
        if selected_ids:
            records = self.env['product.product'].sudo().browse(
                selected_ids).filtered(lambda p: p.woo_id or p.is_exported)
        else:
            self.env['product.product'].sudo().search([
                ('is_exported', '=', True),
                ('woo_id', '!=', False)])

        product_data_list = []
        for rec in records:
            if rec.woo_id:
                product_data_list.append({
                    "id": rec.woo_id,
                    "name": rec.product_tmpl_id.woo_id,
                    'data':{
                        "stock_quantity": rec.qty_available
                    }
                })

        if product_data_list:
            for data in product_data_list:
                try:
                    if data.get('id'):
                        response = wcapi.put(
                            "products/%s/variations/%s" % (data.get('name'), data.get('id')), data.get('data'))
                        if response.status_code != 200:
                            message = response.json().get('message')
                            _logger.error(
                                f"Error al actualizar la variante {data.get('id')}: {message}")
                            raise UserError(
                                _("Error al actualizar variante en WooCommerce"))
                except Exception as error:
                    _logger.error(
                        f"Error durante la exportación de la variante: {str(error)}")
                    raise UserError(
                        _("Error de conexión, por favor intente nuevamente"))
        self.env['product.template'].import_inventory(instance_id)


class Product(models.Model):
    _inherit = 'product.template'

    woo_id = fields.Char('WooCommerce ID')
    woo_regular_price = fields.Float('WooCommerce Regular Price')
    woo_sale_price = fields.Float('WooCommerce Sale Price')
    commission_type = fields.Selection([
        ('global', 'Global'),
        ('percent', 'Percentage'),
        ('fixed', 'Fixed'),
        ('percent_fixed', 'Percent Fixed'),
    ], "Commission Type")
    commission_value = fields.Float("Commission for Admin")
    fixed_commission_value = fields.Float("Fixed Price")
    woo_product_weight = fields.Float("Peso")
    woo_product_length = fields.Float("Largo")
    woo_product_width = fields.Float("Ancho")
    woo_product_height = fields.Float("Alto")
    website_published = fields.Boolean()
    woo_weight_unit = fields.Char(compute='_compute_weight_uom_name')
    woo_unit_other = fields.Char(compute='_compute_length_uom_name')
    woo_image_ids = fields.One2many("woo.product.image", "template_id")
    woo_tag_ids = fields.Many2many(
        "product.tag.woo", relation='product_woo_tags_rel', string="Tags")
    is_exported = fields.Boolean('Synced In Woocommerce', default=False)
    woo_instance_id = fields.Many2one('woo.instance', ondelete='cascade')
    woo_product_qty = fields.Float("Woo Stock Quantity")
    woo_short_description = fields.Html(string="Product Short Description")
    woo_ingredients = fields.Html(string="Ingredients")
    woo_details = fields.Html(string="Details")
    woo_instructions = fields.Html(string="Instructions")
    woo_scientific_ref = fields.Html(string="Scientific References")
    product_category_ids = fields.Many2many(
        "product.category", relation='product_temp_category_rel', string="Categories")
    woo_product_videos = fields.Text("Product Videos")
    wps_subtitle = fields.Char(string="Woo wps subtitle")
    woo_product_attachment = fields.Binary(string="WooCommerce Attachment")

    @api.model
    def _get_volume_uom_id_from_ir_config_parameter(self):
        """ Get the unit of measure to interpret the `volume` field. By default, we consider
        that volumes are expressed in cubic meters. Users can configure to express them in cubic feet
        by adding an ir.config_parameter record with "product.volume_in_cubic_feet" as key
        and "1" as value.
        """
        product_length_in_feet_param = self.env['ir.config_parameter'].sudo(
        ).get_param('product.volume_in_cubic_feet')
        if product_length_in_feet_param == '1':
            return self.env.ref('uom.product_uom_cubic_foot')
        else:
            return self.env.ref('uom.product_uom_cubic_inch')

    def _compute_weight_uom_name(self):
        self.woo_weight_unit = self._get_weight_uom_name_from_ir_config_parameter()
        return super(Product, self)._compute_weight_uom_name()

    @api.model
    def _get_length_uom_id_from_ir_config_parameter(self):
        """ Get the unit of measure to interpret the `length`, 'width', 'height' field.
        By default, we considerer that length are expressed in millimeters. Users can configure
        to express them in feet by adding an ir.config_parameter record with "product.volume_in_cubic_feet"
        as key and "1" as value.
        """
        product_length_in_feet_param = self.env['ir.config_parameter'].sudo(
        ).get_param('product.volume_in_cubic_feet')
        if product_length_in_feet_param == '1':
            return self.env.ref('uom.product_uom_foot')
        else:
            return self.env.ref('uom.product_uom_inch')

    def _compute_length_uom_name(self):
        self.woo_unit_other = self._get_length_uom_name_from_ir_config_parameter()

    def woo_published(self):
        return True

    def woo_unpublished(self):
        return True

    def cron_export_product(self):
        all_instances = self.env['woo.instance'].sudo().search([])
        for rec in all_instances:
            if rec:
                self.env['product.template'].export_selected_product(rec)

    def export_selected_product(self, instance_id):

        location = instance_id.url
        cons_key = instance_id.client_id
        sec_key = instance_id.client_secret
        version = 'wc/v3'
        pass

        wcapi = API(url=location, consumer_key=cons_key,
                    consumer_secret=sec_key, version=version)

        # Filtrar productos seleccionados o exportados con woo_id
        selected_ids = self.env.context.get('active_ids', [])
        if selected_ids:
            records = self.env['product.template'].sudo().browse(
                selected_ids).filtered(lambda p: p.woo_id or p.is_exported)
        else:
            records = self.env['product.template'].sudo().search(
                [('is_exported', '=', True), ('woo_id', '!=', False)])

        if not records:
            raise UserError(
                _("No existen productos exportados o sincronizados para WooCommerce."))

        # Actualizar stock solo si el producto o variante tiene un woo_id
        for rec in records:
            # Productos simples
            if not rec.has_variant:
                # Actualizamos el stock solo para productos simples que ya existen en WooCommerce
                product_data = {
                    "stock_quantity": rec.qty_available,
                }

                try:
                    response = wcapi.put(
                        f"products/{rec.woo_id}", product_data)
                    if response.status_code != 200:
                        message = response.json().get('message', 'Error desconocido')
                        _logger.error(
                            f"Error al actualizar el stock del producto {rec.name}: {message}")
                        raise UserError(
                            _("Error al actualizar el stock en WooCommerce: %s" % message))
                    else:
                        _logger.info(
                            f"Stock del producto {rec.name} actualizado correctamente en WooCommerce.")
                except Exception as error:
                    _logger.error(
                        f"Error durante la exportación del stock del producto {rec.name}: {str(error)}")
                    raise UserError(
                        _("Error de conexión, por favor intente nuevamente"))

            # Variantes
            else:
                # Si el producto tiene variantes, actualizamos el stock de cada variante
                for variant in rec.product_variant_ids.filtered(lambda v: v.woo_id):
                    variant_data = {
                        "stock_quantity": variant.qty_available,
                    }

                    try:
                        response = wcapi.put(
                            f"products/{variant.product_tmpl_id.woo_id}/variations/{variant.woo_id}", variant_data)
                        if response.status_code != 200:
                            message = response.json().get('message', 'Error desconocido')
                            _logger.error(
                                f"Error al actualizar el stock de la variante {variant.name}: {message}")
                            raise UserError(
                                _("Error al actualizar el stock de la variante en WooCommerce: %s" % message))
                        else:
                            _logger.info(
                                f"Stock de la variante {variant.name} actualizado correctamente en WooCommerce.")
                    except Exception as error:
                        _logger.error(
                            f"Error durante la exportación del stock de la variante {variant.name}: {str(error)}")
                        raise UserError(
                            _("Error de conexión, por favor intente nuevamente"))

    def cron_import_product(self):
        all_instances = self.env['woo.instance'].sudo().search([])
        for rec in all_instances:
            if rec:
                self.env['product.template'].import_product(rec)

    def cron_import_inventory(self):
        all_instances = self.env['woo.instance'].sudo().search([])
        for rec in all_instances:
            if rec:
                self.env['product.template'].import_inventory(rec)

    def import_product(self, instance_id):
        page = 1
        while page > 0:
            location = instance_id.url
            cons_key = instance_id.client_id
            sec_key = instance_id.client_secret
            version = 'wc/v3'

            wcapi = API(
                url=location,
                consumer_key=cons_key,
                consumer_secret=sec_key,
                version=version,
                timeout=900
            )

            url = "products"
            try:
                data = wcapi.get(
                    url, params={'orderby': 'id', 'order': 'asc', 'per_page': 100, 'page': page})
                page += 1

            except Exception as error:
                _logger.error(
                    f"Error al conectarse a WooCommerce: {str(error)}. Reintentando...")
                time.sleep(5)
                continue
                # raise UserError(_("Please check your connection and try again"))
            if data.status_code == 200:
                if data.content:
                    parsed_data = data.json()
                    if len(parsed_data) == 0:
                        page = 0
                    if parsed_data:
                        for ele in parsed_data:
                            """ This will avoid duplications of products already
                            having woo_id.
                            """
                            pro_t = []
                            categ_list = []
                            if ele.get('sku'):
                                product = self.env['product.template'].sudo().search(
                                    ['|', ('woo_id', '=', ele.get('id')), ('default_code', '=', ele.get('sku'))], limit=1)
                            else:
                                product = self.env['product.template'].sudo().search(
                                    [('woo_id', '=', ele.get('id'))], limit=1)

                            """ This is used to update woo_id of a product, this
                            will avoid duplication of product while syncing product.
                            """
                            product_without_woo_id = self.env['product.template'].sudo().search(
                                [('woo_id', '=', False), ('default_code', '=', ele.get('sku'))], limit=1)

                            product_product_without_id = self.env['product.product'].sudo().search(
                                [('product_tmpl_id', '=', product_without_woo_id.id)], limit=1)

                            dict_p = {}
                            dict_p['is_exported'] = True
                            dict_p['woo_instance_id'] = instance_id.id
                            dict_p['company_id'] = instance_id.woo_company_id.id
                            dict_p['woo_id'] = ele.get(
                                'id') if ele.get('id') else ''
                            dict_p['name'] = ele.get(
                                'name') if ele.get('name') else ''
                            if ele.get('description'):
                                parsed_desc = ele.get('description').replace(
                                    '<h1>', '<h6>').replace('</h1>', '</h6>')
                                parsed_desc = parsed_desc.replace(
                                    '<h2>', '<h6>').replace('</h2>', '</h6>')
                                parsed_desc = parsed_desc.replace(
                                    '<h3>', '<h6>').replace('</h3>', '</h6>')
                                # dict_p['description'] = parsed_desc
                                soup = BeautifulSoup(
                                    ele.get('description'), 'html.parser')
                                description_converted_to_text = soup.get_text()
                                # dict_p['description_sale'] = description_converted_to_text
                            dict_p['default_code'] = ele.get(
                                'sku') if ele.get('sku') else ''

                            # for rec in ele.get('categories'):
                            #     categ = self.env['product.category'].sudo().search([('woo_id', '=', rec.get('id'))], limit=1)
                            #     if categ and categ.id not in categ_list:
                            #         categ_list.append(categ.id)
                            # if ele.get('categories') and ele.get('categories')[0].get('name'):
                            #     categ = self.env['product.category'].sudo().search([('name', '=', ele.get('categories')[0].get('name'))], limit=1)
                            #     if categ:
                            #         dict_p['categ_id'] = categ[0].id

                            dict_p['list_price'] = ele.get(
                                'price') if ele.get('price') else 0.0
                            dict_p['woo_sale_price'] = ele.get(
                                'price') if ele.get('price') else 0.0
                            dict_p['woo_regular_price'] = ele.get(
                                'price') if ele.get('price') else 0.0
                            # if ele.get('purchaseable') and ele.get('purchaseable') == True else True
                            dict_p['purchase_ok'] = False
                            # if ele.get('on_sale') and ele.get('on_sale') == True else False
                            dict_p['sale_ok'] = True
                            dict_p['qty_available'] = True if ele.get(
                                'stock_quantity') else 0.00

                            # if ele.get('images'):
                            #     url = ele.get('images')[0].get('src')
                            #     response = requests.get(url)
                            #     if imghdr.what(None, response.content) != 'webp':
                            #         image = base64.b64encode(requests.get(url).content)
                            #         dict_p['image_1920'] = image

                            dict_p['weight'] = float(
                                ele.get('weight')) if ele.get('weight') else 0.00
                            dict_p['woo_product_weight'] = float(
                                ele.get('weight')) if ele.get('weight') else 0.00
                            dict_p['woo_product_length'] = float(ele.get('dimensions').get('length')) if ele.get(
                                'dimensions') and ele.get('dimensions').get('length') else 0.00
                            dict_p['woo_product_width'] = float(ele.get('dimensions').get('width')) if ele.get(
                                'dimensions') and ele.get('dimensions').get('width') else 0.00
                            dict_p['woo_product_height'] = float(ele.get('dimensions').get('height')) if ele.get(
                                'dimensions') and ele.get('dimensions').get('height') else 0.00

                            if ele.get('tags'):
                                for rec in ele.get('tags'):
                                    existing_tag = self.env['product.tag.woo'].sudo().search(
                                        ['|', ('woo_id', '=', rec.get('id')), ('name', '=', rec.get('name'))], limit=1)
                                    dict_value = {}
                                    dict_value['is_exported'] = True
                                    dict_value['woo_instance_id'] = instance_id.id
                                    dict_value['name'] = rec.get(
                                        'name') if rec.get('name') else ''
                                    dict_value['woo_id'] = rec.get(
                                        'id') if rec.get('id') else ''
                                    dict_value['description'] = rec.get(
                                        'description') if rec.get('description') else ''
                                    dict_value['slug'] = rec.get(
                                        'slug') if rec.get('slug') else ''

                                    if not existing_tag:
                                        create_tag_value = self.env['product.tag.woo'].sudo().create(
                                            dict_value)
                                        pro_t.append(create_tag_value.id)
                                    else:
                                        write_tag_value = existing_tag.sudo().write(dict_value)
                                        pro_t.append(existing_tag.id)

                            if not product and product_without_woo_id:
                                product_without_woo_id.sudo().write(dict_p)
                                if product_product_without_id and not ele.get('variations'):
                                    product_product_without_id.sudo().write({
                                        'is_exported': True,
                                        'woo_id': dict_p['woo_id'],
                                        'woo_sale_price': product_without_woo_id.woo_sale_price,
                                        'default_code': ele.get('sku'),
                                        'qty_available': dict_p['qty_available']
                                    })

                            if product and not product_without_woo_id:
                                product.sudo().write(dict_p)

                            if not product and not product_without_woo_id:
                                dict_p['type'] = 'product'
                                '''If product is not present we create it'''
                                pro_create = self.env['product.template'].create(
                                    dict_p)
                                product_product_vr = self.env['product.product'].sudo().search(
                                    [('product_tmpl_id', '=', pro_create.id)])
                                if product_product_vr and not ele.get('variations'):
                                    product_product_vr.sudo().write({
                                        'is_exported': True,
                                        'woo_id': dict_p['woo_id'],
                                        'woo_sale_price': pro_create.woo_sale_price,
                                        'default_code': ele.get('sku'),
                                        'qty_available': dict_p['qty_available']
                                    })
                                if pro_t:
                                    pro_create.woo_tag_ids = [
                                        (4, val) for val in pro_t]

                                if pro_create:
                                    for rec in ele.get('meta_data'):
                                        if rec.get('key') == '_wcfm_product_author':
                                            vendor_id = rec.get('value')
                                            vendor_odoo_id = self.env['res.partner'].sudo().search([('woo_id', '=', vendor_id)],
                                                                                                   limit=1)
                                            if vendor_odoo_id:
                                                seller = self.env['product.supplierinfo'].sudo().create({
                                                    'name': vendor_odoo_id.id,
                                                    'product_id': pro_create.id
                                                })
                                                pro_create.seller_ids = [
                                                    (6, 0, [seller.id])]

                                        if rec.get('key') == '_wcfmmp_commission':
                                            pro_create.commission_type = rec.get(
                                                'value').get('commission_mode')
                                            if pro_create.commission_type == 'percent':
                                                pro_create.commission_value = rec.get(
                                                    'value').get('commission_percent')
                                            elif pro_create.commission_type == 'fixed':
                                                pro_create.fixed_commission_value = rec.get(
                                                    'value').get('commission_fixed')
                                            elif pro_create.commission_type == 'percent_fixed':
                                                pro_create.commission_value = rec.get(
                                                    'value').get('commission_percent')
                                                pro_create.fixed_commission_value = rec.get(
                                                    'value').get('commission_fixed')

                                    if ele.get('attributes'):
                                        dict_attr = {}
                                        for rec in ele.get('attributes'):
                                            product_attr = self.env['product.attribute'].sudo().search(
                                                ['|', ('woo_id', '=', rec.get(
                                                    'id')), ('name', '=', rec.get('name'))],
                                                limit=1)
                                            dict_attr['is_exported'] = True
                                            dict_attr['woo_instance_id'] = instance_id.id
                                            dict_attr['woo_id'] = rec.get(
                                                'id') if rec.get('id') else ''
                                            dict_attr['name'] = rec.get(
                                                'name') if rec.get('name') else ''
                                            dict_attr['slug'] = rec.get(
                                                'slug') if rec.get('slug') else ''
                                            if not product_attr:
                                                product_attr = self.env['product.attribute'].sudo().create(
                                                    dict_attr)

                                            pro_val = []
                                            if rec.get('options'):
                                                for value in rec.get('options'):
                                                    existing_attr_value = self.env['product.attribute.value'].sudo().search(
                                                        [('name', '=', value), ('attribute_id', '=', product_attr.id)], limit=1)
                                                    dict_value = {}
                                                    dict_value['is_exported'] = True
                                                    dict_value['woo_instance_id'] = instance_id.id
                                                    dict_value['name'] = value if value else ''
                                                    dict_value['attribute_id'] = product_attr.id

                                                    if not existing_attr_value and dict_value['attribute_id']:
                                                        create_value = self.env['product.attribute.value'].sudo().create(
                                                            dict_value)
                                                        pro_val.append(
                                                            create_value.id)
                                                    elif existing_attr_value:
                                                        write_value = existing_attr_value.sudo().write(
                                                            dict_value)
                                                        pro_val.append(
                                                            existing_attr_value.id)

                                            if product_attr:
                                                if pro_val:
                                                    exist = self.env['product.template.attribute.line'].sudo().search(
                                                        [('attribute_id', '=', product_attr.id),
                                                         ('value_ids',
                                                          'in', pro_val),
                                                         ('product_tmpl_id', '=', pro_create.id)], limit=1)
                                                    if not exist:
                                                        create_attr_line = self.env[
                                                            'product.template.attribute.line'].sudo().create({
                                                                'attribute_id': product_attr.id,
                                                                'value_ids': [(6, 0, pro_val)],
                                                                'product_tmpl_id': pro_create.id
                                                            })
                                                    else:
                                                        exist.sudo().write({
                                                            'attribute_id': product_attr.id,
                                                            'value_ids': [(6, 0, pro_val)],
                                                            'product_tmpl_id': pro_create.id
                                                        })

                                    if ele.get('variations'):
                                        url = location + '/wp-json/wc/v3'
                                        consumer_key = cons_key
                                        consumer_secret = sec_key
                                        session = requests.Session()
                                        session.auth = (
                                            consumer_key, consumer_secret)
                                        product_id = ele.get('id')
                                        endpoint = f"{url}/products/{product_id}/variations"
                                        response = session.get(endpoint)
                                        if response.status_code == 200:
                                            parsed_variants_data = json.loads(
                                                response.text)
                                            variant_list = []
                                            product_variant = self.env['product.product'].sudo().search(
                                                [('product_tmpl_id', '=', pro_create.id)])

                                            lines_without_no_variants = pro_create.valid_product_template_attribute_line_ids._without_no_variant_attributes()
                                            all_variants = pro_create.with_context(
                                                active_test=False).product_variant_ids.sorted(
                                                lambda p: (p.active, -p.id))
                                            single_value_lines = lines_without_no_variants.filtered(
                                                lambda ptal: len(ptal.product_template_value_ids._only_active()) == 1)
                                            if single_value_lines:
                                                for variant in all_variants:
                                                    combination = variant.product_template_attribute_value_ids | single_value_lines.product_template_value_ids._only_active()

                                            all_combinations = itertools.product(*[
                                                ptal.product_template_value_ids._only_active() for ptal in
                                                lines_without_no_variants
                                            ])

                                            if parsed_variants_data:
                                                for variant in parsed_variants_data:
                                                    list_1 = []
                                                    for var in variant.get('attributes'):
                                                        list_1.append(
                                                            var.get('option'))
                                                    for item in product_variant:
                                                        if item.product_template_attribute_value_ids:
                                                            list_values = []
                                                            for rec in item.product_template_attribute_value_ids:
                                                                if list_1 and rec.name == list_1[0]:
                                                                    price_extra = item.lst_price - float(variant.get('sale_price')) if variant.get(
                                                                        'sale_price') else item.lst_price - float(variant.get('regular_price'))
                                                                    if price_extra >= 0:
                                                                        rec.price_extra = price_extra
                                                                    else:
                                                                        rec.price_extra = - \
                                                                            (price_extra)
                                                                list_values.append(
                                                                    rec.name)
                                                            if set(list_1).issubset(list_values):
                                                                item.default_code = variant.get(
                                                                    'sku')
                                                                item.woo_sale_price = variant.get('sale_price') if variant.get(
                                                                    'sale_price') else variant.get('regular_price')
                                                                item.woo_regular_price = variant.get(
                                                                    'regular_price')
                                                                item.woo_id = variant.get(
                                                                    'id')
                                                                item.woo_instance_id = instance_id
                                                                item.qty_available = variant.get(
                                                                    'stock_quantity')
                                                                item.woo_product_weight = variant.get(
                                                                    'weight')
                                                                item.weight = variant.get(
                                                                    'weight')
                                                                item.is_exported = True
                                                                if variant.get('dimensions'):
                                                                    if variant.get('dimensions').get('length'):
                                                                        item.woo_product_length = variant.get(
                                                                            'dimensions').get('length')
                                                                    if variant.get('dimensions').get('width'):
                                                                        item.woo_product_width = variant.get(
                                                                            'dimensions').get('width')
                                                                    if variant.get('dimensions').get('height'):
                                                                        item.woo_product_height = variant.get(
                                                                            'dimensions').get('height')
                                                                    item.volume = item.woo_product_length * \
                                                                        item.woo_product_width * item.woo_product_height
                                                                if variant.get('description'):
                                                                    item.woo_varient_description = variant.get(
                                                                        'description').replace('<p>', '').replace('</p>',
                                                                                                                  '')
                                                                    item.description = variant.get(
                                                                        'description')
                                                                    item.description_sale = variant.get(
                                                                        'description').replace('<p>', '').replace('</p>', '')
                                                                # else:
                                                                #     item.description = item.name
                                                for combination_tuple in all_combinations:
                                                    combination = self.env['product.template.attribute.value'].concat(
                                                        *combination_tuple)
                                                    list_var = []
                                                    for n in combination:
                                                        list_var.append(n.name)

                                    pro_create.default_code = ele.get('sku')
                                self.env.cr.commit()
                            else:
                                product = product or product_without_woo_id
                                pro_create = product.sudo().write(dict_p)

                                product_product = self.env['product.product'].sudo().search(
                                    [('product_tmpl_id', '=', product.id)], limit=1)
                                if product_product and not ele.get('variations'):
                                    product_product.sudo().write({
                                        'is_exported': True,
                                        'woo_id': dict_p['woo_id'],
                                        'woo_sale_price': product.woo_sale_price,
                                        'default_code': dict_p['default_code'],
                                        'qty_available': dict_p['qty_available']

                                    })

                                if pro_t:
                                    product.woo_tag_ids = [
                                        (4, val) for val in pro_t]

                                if ele.get('attributes'):
                                    dict_attr = {}
                                    for rec in ele.get('attributes'):
                                        product_attr = self.env['product.attribute'].sudo().search(
                                            ['|', ('woo_id', '=', rec.get('id')), ('name', '=', rec.get('name'))], limit=1)
                                        dict_attr['is_exported'] = True
                                        dict_attr['woo_instance_id'] = instance_id.id
                                        dict_attr['woo_id'] = rec.get(
                                            'id') if rec.get('id') else ''
                                        dict_attr['name'] = rec.get(
                                            'name') if rec.get('name') else ''
                                        dict_attr['slug'] = rec.get(
                                            'slug') if rec.get('slug') else ''
                                        if not product_attr:
                                            product_attr = self.env['product.attribute'].sudo().create(
                                                dict_attr)

                                        pro_val = []
                                        if rec.get('options'):
                                            for value in rec.get('options'):
                                                existing_attr_value = self.env['product.attribute.value'].sudo().search(
                                                    [('name', '=', value), ('attribute_id', '=', product_attr.id)], limit=1)
                                                dict_value = {}
                                                dict_value['is_exported'] = True
                                                dict_value['woo_instance_id'] = instance_id.id
                                                dict_value['name'] = value if value else ''
                                                dict_value['attribute_id'] = product_attr.id

                                                if not existing_attr_value and dict_value['attribute_id']:
                                                    create_value = self.env['product.attribute.value'].sudo().create(
                                                        dict_value)
                                                    pro_val.append(
                                                        create_value.id)

                                                elif existing_attr_value:
                                                    write_value = self.env['product.attribute.value'].sudo().write(
                                                        dict_value)
                                                    pro_val.append(
                                                        existing_attr_value.id)

                                        if product_attr:
                                            if pro_val:
                                                exist = self.env['product.template.attribute.line'].sudo().search(
                                                    [('attribute_id', '=', product_attr.id), ('value_ids', 'in', pro_val),
                                                     ('product_tmpl_id', '=', product.id)], limit=1)
                                                if not exist:
                                                    create_attr_line = self.env['product.template.attribute.line'].sudo().create(
                                                        {'attribute_id': product_attr.id, 'value_ids': [(6, 0, pro_val)],
                                                         'product_tmpl_id': product.id})
                                                else:
                                                    exist.sudo().write(
                                                        {'attribute_id': product_attr.id, 'value_ids': [(6, 0, pro_val)],
                                                         'product_tmpl_id': product.id})

                                if ele.get('variations'):
                                    url = location + '/wp-json/wc/v3'
                                    consumer_key = cons_key
                                    consumer_secret = sec_key
                                    session = requests.Session()
                                    session.auth = (
                                        consumer_key, consumer_secret)
                                    product_id = ele.get('id')
                                    endpoint = f"{url}/products/{product_id}/variations"
                                    params = {
                                        'orderby': 'date',
                                        'order': 'asc',
                                        'per_page': 100,
                                        'page': 1
                                    }

                                    response = session.get(
                                        endpoint, params=params)
                                    if response.status_code == 200:
                                        parsed_variants_data = json.loads(
                                            response.text)
                                        product_variant = self.env['product.product'].sudo().search(
                                            [('product_tmpl_id', '=', product.id)])

                                        lines_without_no_variants = product.valid_product_template_attribute_line_ids._without_no_variant_attributes()
                                        all_variants = product.with_context(active_test=False).product_variant_ids.sorted(
                                            lambda p: (p.active, -p.id))
                                        single_value_lines = lines_without_no_variants.filtered(
                                            lambda ptal: len(ptal.product_template_value_ids._only_active()) == 1)
                                        if single_value_lines:
                                            for variant in all_variants:
                                                combination = variant.product_template_attribute_value_ids | single_value_lines.product_template_value_ids._only_active()

                                        all_combinations = itertools.product(*[
                                            ptal.product_template_value_ids._only_active() for ptal in
                                            lines_without_no_variants
                                        ])

                                        if parsed_variants_data:
                                            for variant in parsed_variants_data:
                                                list_1 = []
                                                for var in variant.get('attributes'):
                                                    list_1.append(
                                                        var.get('option'))
                                                for item in product_variant:
                                                    if item.product_template_attribute_value_ids:
                                                        list_values = []
                                                        for rec in item.product_template_attribute_value_ids:
                                                            if list_1 and rec.name == list_1[0]:
                                                                if item.lst_price != item.woo_sale_price:
                                                                    price_extra = item.lst_price - float(variant.get('sale_price')) if variant.get(
                                                                        'sale_price') else item.lst_price - float(variant.get('regular_price'))
                                                                    if price_extra >= 0:
                                                                        rec.price_extra = price_extra
                                                                    else:
                                                                        rec.price_extra = - \
                                                                            (price_extra)
                                                            list_values.append(
                                                                rec.name)

                                                        if set(list_1).issubset(list_values):
                                                            item.default_code = variant.get(
                                                                'sku')
                                                            item.woo_sale_price = variant.get('sale_price') if variant.get(
                                                                'sale_price') else variant.get('regular_price')
                                                            item.woo_regular_price = variant.get(
                                                                'regular_price')
                                                            item.woo_id = variant.get(
                                                                'id')
                                                            item.woo_instance_id = instance_id
                                                            item.qty_available = variant.get(
                                                                'stock_quantity')
                                                            item.woo_product_weight = variant.get(
                                                                'weight')
                                                            item.weight = variant.get(
                                                                'weight')
                                                            item.is_exported = True
                                                            if variant.get('dimensions'):
                                                                if variant.get('dimensions').get('length'):
                                                                    item.woo_product_length = variant.get(
                                                                        'dimensions').get('length')
                                                                if variant.get('dimensions').get('width'):
                                                                    item.woo_product_width = variant.get(
                                                                        'dimensions').get('width')
                                                                if variant.get('dimensions').get('height'):
                                                                    item.woo_product_height = variant.get(
                                                                        'dimensions').get('height')
                                                                item.volume = item.woo_product_length * \
                                                                    item.woo_product_width * item.woo_product_height
                                                            if variant.get('description'):
                                                                item.woo_varient_description = variant.get(
                                                                    'description').replace('<p>', '').replace('</p>', '')
                                                                item.description = variant.get(
                                                                    'description')
                                                                item.description_sale = variant.get(
                                                                    'description').replace('<p>', '').replace('</p>',
                                                                                                              '')
                                                            else:
                                                                item.description = item.name
                                            for combination_tuple in all_combinations:
                                                combination = self.env['product.template.attribute.value'].concat(
                                                    *combination_tuple)
                                                list_var = []
                                                for n in combination:
                                                    list_var.append(n.name)

                                product.default_code = ele.get('sku')

                                for rec in ele.get('meta_data'):
                                    if rec.get('key') == '_wcfm_product_author':
                                        vendor_id = rec.get('value')
                                        vendor_odoo_id = self.env['res.partner'].sudo().search([('woo_id', '=', vendor_id)],
                                                                                               limit=1)
                                        if vendor_odoo_id:
                                            vendor_supplier_info = self.env['product.supplierinfo'].sudo().search(
                                                [('name', '=', vendor_odoo_id.id),
                                                 ('product_id', '=', product.id)],
                                                limit=1)
                                            if not vendor_supplier_info:
                                                seller = self.env['product.supplierinfo'].sudo().create({
                                                    'name': vendor_odoo_id.id,
                                                    'product_id': product.id
                                                })
                                                product.seller_ids = [
                                                    (6, 0, [seller.id])]

                                    if rec.get('key') == '_wcfmmp_commission':
                                        product.commission_type = rec.get(
                                            'value').get('commission_mode')
                                        if product.commission_type == 'percent':
                                            product.commission_value = rec.get(
                                                'value').get('commission_percent')
                                        elif product.commission_type == 'fixed':
                                            product.fixed_commission_value = rec.get(
                                                'value').get('commission_fixed')
                                        elif product.commission_type == 'percent_fixed':
                                            product.commission_value = rec.get(
                                                'value').get('commission_percent')
                                            product.fixed_commission_value = rec.get(
                                                'value').get('commission_fixed')
                                self.env.cr.commit()
                else:
                    page = 0
            else:
                page = 0

    def import_inventory(self, instance_id):
        page = 1
        location_id = self.env.ref('stock.stock_location_stock').id
        while page > 0:
            location = instance_id.url
            cons_key = instance_id.client_id
            sec_key = instance_id.client_secret
            version = 'wc/v3'

            wcapi = API(url=location,
                        consumer_key=cons_key,
                        consumer_secret=sec_key,
                        version=version,
                        timeout=900
                        )
            url = "products"
            try:
                data = wcapi.get(
                    url, params={'orderby': 'id', 'order': 'asc', 'per_page': 100, 'page': page})
                page += 1
            except Exception as error:
                raise UserError(
                    _("Please check your connection and try again"))

            if data.status_code == 200 and data.content:
                parsed_data = data.json()
                if len(parsed_data) == 0:
                    page = 0
                for ele in parsed_data:
                    # Repetir para las variantes del producto
                    product_template = self.env['product.template'].sudo().search(
                        ['|', ('woo_id', '=', ele.get('id')), ('default_code', '=', ele.get('sku'))], limit=1)
                    # Si el producto existe en Odoo
                    if product_template:
                        if ele.get('type') == 'variable':
                            # Obtener las variaciones si el producto es variable
                            try:
                                variations_data = wcapi.get(
                                    f'products/{product_template.woo_id}/variations')
                                if variations_data.status_code == 200:
                                    variations = variations_data.json()
                                    if not variations:
                                        _logger.warning(
                                            f"El producto {product_template.name} no tiene variaciones en WooCommerce.")
                                        continue
                                    for var in variations:
                                        stock_quantity = var.get(
                                            'stock_quantity')
                                        if stock_quantity is not None and stock_quantity >= 0:
                                            product_variant = self.env['product.product'].sudo().search(
                                                ['|', ('woo_id', '=', var.get('id')), ('default_code', '=', var.get('sku'))], limit=1)
                                            if product_variant:
                                                self._update_stock_quantities(
                                                    product_variant, stock_quantity, location_id)
                            except Exception as error:
                                _logger.error(
                                    f"Error al obtener las variantes del producto {product_template.name} desde WooCommerce: {error}")
                                raise UserError(
                                    _("Error al obtener las variantes del producto %s desde WooCommerce" % product_template.name))
                        elif ele.get('type') == 'simple':
                            stock_quantity = ele.get('stock_quantity')
                            if stock_quantity is not None and stock_quantity >= 0:
                                product = self.env['product.product'].sudo().search(
                                    ['|', ('woo_id', '=', var.get('id')), ('default_code', '=', var.get('sku'))], limit=1)
                                if product:
                                    self._update_stock_quantities(
                                        product, stock_quantity, location_id)
            else:
                page = 0

    def _update_stock_quantities(self, product, stock_quantity, location_id):
        """Actualiza las cantidades de stock según si el producto tiene seguimiento por lotes o no."""

        if product.tracking != 'none':
            # Procesamos las cantidades de stock por lote
            lots = self.env['stock.lot'].sudo().search(
                [('product_id', '=', product.id)], order='create_date asc')
            if not lots:
                _logger.warning(
                    f"No hay lotes disponibles para el producto {product.name}. Creando un nuevo lote.")
                lot = self.env['stock.lot'].sudo().create({
                    'name': f"L000-{product.default_code}",
                    'product_id': product.id,
                    'company_id': self.env.company.id
                })
                self.env['stock.quant'].sudo().create({
                    'product_id': product.id,
                    'location_id': location_id,
                    'quantity': stock_quantity,
                    'lot_id': lot.id,
                    'company_id': self.env.company.id
                })
                return
            else:
                oldest_lot = lots[0]

            # Obtengo las cantidades de stock actuales para los lotes existentes
            total_quantity_in_lots = sum(self.env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', '=', location_id),
                ('lot_id', '=', lots.id)
            ]).mapped('quantity'))

            difference = stock_quantity - total_quantity_in_lots

            if difference > 0:
                quant = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', product.id),
                    ('location_id', '=', location_id),
                    ('lot_id', '=', oldest_lot.id),
                ], limit=1)
                if quant:
                    quant.sudo().write(
                        {'quantity': quant.quantity + difference})
                else:
                    self.env['stock.quant'].sudo().create({
                        'product_id': product.id,
                        'location_id': location_id,
                        'quantity': difference,
                        'lot_id': oldest_lot.id,
                        'company_id': self.env.company.id
                    })
            elif difference < 0:
                quant = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', product.id),
                    ('location_id', '=', location_id),
                    ('lot_id', '=', oldest_lot.id)
                ], limit=1)
                if quant and quant.quantity >= abs(difference):
                    quant.sudo().write(
                        {'quantity': quant.quantity + difference})
                else:
                    raise UserError(
                        _("No se puede reducir más stock del lote más antiguo porque la cantidad es insuficiente."))
        else:
            quant = self.env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', '=', location_id)
            ], limit=1)

            if quant:
                quant.sudo().write({'quantity': stock_quantity})
            else:
                self.env['stock.quant'].sudo().create({
                    'product_id': product.id,
                    'location_id': location_id,
                    'quantity': stock_quantity,
                    'company_id': self.env.company.id
                })

    # def sync_stock_with_woo(self, instance_id):
    #     location = instance_id.url
    #     cons_key = instance_id.client_id
    #     sec_key = instance_id.client_secret
    #     version = 'wc/v3'

    #     wcapi = API(
    #         url=location,
    #         consumer_key=cons_key,
    #         consumer_secret=sec_key,
    #         version=version)

    #     for product in self:
    #         if product.woo_id and product.woo_instance_id:
    #             for variant in
