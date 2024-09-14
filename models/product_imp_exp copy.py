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
    template_id = fields.Many2one('product.template', string='Product template', ondelete='cascade')
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
                    raise UserError(_("Please provide valid Image URL with any extension."))
                else:
                    photo = base64.encodebytes(urlopen(self.url).read())
                    self.image = photo

            except Exception as error:
                raise UserError(_("Invalid Url"))


class ProductProduct(models.Model):
    _inherit = 'product.product'

    woo_id = fields.Char('WooCommerce ID')
    woo_regular_price = fields.Float('WooCommerce Regular Price')
    #DB woo_product_weight = fields.Float("Woo Weight")
    # woo_product_length = fields.Float("Woo Length")
    # woo_product_width = fields.Float("Woo Width")
    # woo_product_height = fields.Float("Woo Height")
    # woo_weight_unit = fields.Char(compute='_compute_weight_uom_name')
    # woo_unit_other = fields.Char(compute='_compute_length_uom_name')
    is_exported = fields.Boolean('Sincronizado con Woocommerce', default=False)
    woo_instance_id = fields.Many2one('woo.instance', ondelete='cascade')
    woo_varient_description = fields.Text('Woo Variant Description')
    default_code = fields.Char('Internal Reference', index=True, required=False)
    woo_sale_price = fields.Float('WooCommerce Sales Price')
    wps_subtitle = fields.Char(string="Woo wps subtitle")

    def cron_export_product(self):
        all_instances = self.env['woo.instance'].sudo().search([])
        for rec in all_instances:
            if rec:
                self.env['product.product'].export_selected_product(rec)

    def export_selected_product_variant(self, instance_id):
        location = instance_id.url
        cons_key = instance_id.client_id
        sec_key = instance_id.client_secret
        version = 'wc/v3'

        wcapi = API(url=location, consumer_key=cons_key, consumer_secret=sec_key, version=version)

        selected_ids = self.env.context.get('active_ids', [])
        if selected_ids:
            records = self.env['product.product'].sudo().browse([selected_ids]).filtered(lambda p: p.woo_id or p.is_exported)
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
                    "manage_stock": True,
                    "stock_quantity": rec.qty_available
                })

        if product_data_list:
            for data in product_data_list:
                try:
                    if data.get('id'):
                        response = wcapi.put("products/%s/variations/%s" % (data.get('name'), data.get('id')), data)
                        if response.status_code != 200:
                            message = response.json().get('message')
                            _logger.error(f"Error al actualizar la variante {data.get('id')}: {message}")
                            raise UserError(_("Error al actualizar variante en WooCommerce"))
                    else:
                        data.pop('id')
                        response = wcapi.post(f"products/{int(data.get('name'))}/variations", data)
                        if response.status_code != 200:
                            message = response.json().get('message')
                            _logger.error(f"Error al crear variante: {message}")
                            raise UserError(_("Error al crear variante en WooCommerce"))
                except Exception as error:
                    _logger.error(f"Error durante la exportación de la variante: {str(error)}")
                    raise UserError(_("Error de conexión, por favor intente nuevamente"))
        self.env['product.template'].import_product(instance_id)


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
    woo_weight_unit = fields.Char(compute='_compute_weight_uom_name')
    woo_unit_other = fields.Char(compute='_compute_length_uom_name')
    woo_image_ids = fields.One2many("woo.product.image", "template_id")
    woo_tag_ids = fields.Many2many("product.tag.woo", relation='product_woo_tags_rel', string="Tags")
    is_exported = fields.Boolean('Synced In Woocommerce', default=False)
    woo_instance_id = fields.Many2one('woo.instance', ondelete='cascade')
    woo_product_qty = fields.Float("Woo Stock Quantity")
    woo_short_description = fields.Html(string="Product Short Description")
    woo_ingredients = fields.Html(string="Ingredients")
    woo_details = fields.Html(string="Details")
    woo_instructions = fields.Html(string="Instructions")
    woo_scientific_ref = fields.Html(string="Scientific References")
    product_category_ids = fields.Many2many("product.category", relation='product_temp_category_rel', string="Categories")
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
        product_length_in_feet_param = self.env['ir.config_parameter'].sudo().get_param('product.volume_in_cubic_feet')
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
        product_length_in_feet_param = self.env['ir.config_parameter'].sudo().get_param('product.volume_in_cubic_feet')
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

        wcapi = API(url=location, consumer_key=cons_key, consumer_secret=sec_key, version=version)

        # Filtrar productos seleccionados o exportados con woo_id
        selected_ids = self.env.context.get('active_ids', [])
        if selected_ids:
            records = self.env['product.template'].sudo().browse(selected_ids).filtered(lambda p: p.woo_id or p.is_exported)
        else:
            records = self.env['product.template'].sudo().search([('is_exported', '=', True), ('woo_id', '!=', False)])

        if not records:
            raise UserError(_("No existen productos exportados o sincronizados para WooCommerce."))

        # Actualizar stock solo si el producto o variante tiene un woo_id
        for rec in records:
            # Productos simples
            if not rec.has_variant:
                # Actualizamos el stock solo para productos simples que ya existen en WooCommerce
                product_data = {
                    "id": rec.woo_id,
                    "manage_stock": True,
                    "stock_quantity": rec.qty_available,
                }

                try:
                    response = wcapi.put(f"products/{product_data.get('id')}", product_data)
                    if response.status_code != 200:
                        message = response.json().get('message', 'Error desconocido')
                        _logger.error(f"Error al actualizar el stock del producto {rec.name}: {message}")
                        raise UserError(_("Error al actualizar el stock en WooCommerce: %s" % message))
                    else:
                        _logger.info(f"Stock del producto {rec.name} actualizado correctamente en WooCommerce.")
                except Exception as error:
                    _logger.error(f"Error durante la exportación del stock del producto {rec.name}: {str(error)}")
                    raise UserError(_("Error de conexión, por favor intente nuevamente"))

            # Variantes
            else:
                # Si el producto tiene variantes, actualizamos el stock de cada variante
                for variant in rec.product_variant_ids.filtered(lambda v: v.woo_id):
                    variant_data = {
                        "id": variant.woo_id,
                        "manage_stock": True,
                        "stock_quantity": variant.qty_available,
                    }

                    try:
                        response = wcapi.put(f"products/{variant.product_tmpl_id.woo_id}/variations/{variant.woo_id}", variant_data)
                        if response.status_code != 200:
                            message = response.json().get('message', 'Error desconocido')
                            _logger.error(f"Error al actualizar el stock de la variante {variant.name}: {message}")
                            raise UserError(_("Error al actualizar el stock de la variante en WooCommerce: %s" % message))
                        else:
                            _logger.info(f"Stock de la variante {variant.name} actualizado correctamente en WooCommerce.")
                    except Exception as error:
                        _logger.error(f"Error durante la exportación del stock de la variante {variant.name}: {str(error)}")
                        raise UserError(_("Error de conexión, por favor intente nuevamente"))

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
        max_retries = 3
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
            retries = 0
            while retries < max_retries:
                try:
                    data = wcapi.get(url, params={'orderby': 'id', 'order': 'asc','per_page': 100, 'page': page})
                    page += 1
                    break

                except Exception as error:
                    _logger.error(f"Error al conectarse a WooCommerce: {str(error)}. Reintentando...")
                    retries += 1
                    time.sleep(5)
                    if retries >= max_retries:
                        _logger.error(f"Max reintentos alcanzado para la página {page}")
                        return
            if data.status_code == 200:
                response = data.json()
                # Si no hay más productos, detener la paginacion
                if not response:
                    break
            
                for ele in response:
                    pro_t = []
                    woo_id = ele.get('id')
                    sku = ele.get('sku')
                    name = ele.get('name')
                    price = ele.get('price') if ele.get('price') else 0.0
                    woo_regular_price = ele.get('regular_price') if ele.get('regular_price') else 0.0
                    woo_sale_price = ele.get('sale_price') if ele.get('sale_price') else 0.0
                    purchase_ok = False
                    sale_ok = True
                    qty_available = True if ele.get('stock_quantity') else 0.00

                    weight = float(ele.get('weight')) if ele.get('weight') else 0.00
                    woo_product_weight = float(ele.get('weight')) if ele.get('weight') else 0.00
                    woo_product_length = float(ele.get('dimensions').get('length'))  if ele.get('dimensions') and ele.get('dimensions').get('length') else 0.00
                    woo_product_width = float(ele.get('dimensions').get('width')) if ele.get('dimensions') and ele.get('dimensions').get('width') else 0.00
                    woo_product_height = float(ele.get('dimensions').get('height')) if ele.get('dimensions') and ele.get('dimensions').get('height') else 0.00

                    if ele.get('tags'):
                        for rec in ele.get('tags'):
                            existing_tag = self.env['product.tag.woo'].sudo().search(['|', ('woo_id', '=', rec.get('id')), ('name', '=', rec.get('name'))], limit=1)
                            dict_value = {
                                'is_exported':True,
                                'woo_instance_id': instance_id.id,
                                'name': rec.get('name') if rec.get('name') else '',
                                'woo_id':rec.get('id') if rec.get('id') else '',
                                'description': rec.get('description') if rec.get('description') else '',
                                'slug': rec.get('slug') if rec.get('slug') else ''
                                }
                            if not existing_tag:
                                create_tag_value = self.env['product.tag.woo'].sudo().create(dict_value)
                                pro_t.append(create_tag_value.id)
                            else:
                                existing_tag.sudo().write(dict_value)
                                pro_t.append(existing_tag.id)
                    

                    # Verificar si el producto ya existe en Odoo usando 'woo_id' o 'sku'
                    product_template = self.env['product.template'].sudo().search(
                        ['|', ('woo_id', '=', woo_id), ('default_code', '=', sku)], limit=1)
                    if not product_template:
                        # Tratamiento específico para productos con variantes
                        if ele.get('type') == 'variable':
                            # Crear plantilla de producto con variantes
                            product_template = self.env['product.template'].sudo().create({
                                'woo_id': woo_id,
                                'name': name,
                                'default_code': sku,
                                'list_price': price,
                                'woo_regular_price': woo_regular_price,
                                'woo_sale_price': woo_sale_price,
                                'type': 'product',
                                'weight': weight,
                                'woo_product_weight': woo_product_weight,
                                'woo_product_length': woo_product_length,
                                'woo_product_width': woo_product_width,
                                'woo_product_height': woo_product_height,
                                'purchase_ok':purchase_ok,
                                'sale_ok':sale_ok
                            })
                            if pro_t:
                                product_template.woo_tag_ids = [(4, val) for val in pro_t]
                            if ele.get('attributes'):
                                dict_attr={}
                                for rec in ele.get('attributes'):
                                    product_attr = self.env['product.attribute'].sudo().search(
                                        ['|', ('woo_id', '=', rec.get('id')), ('name', '=', rec.get('name'))],
                                        limit=1)
                                    dict_attr= {
                                        'is_exported': True,
                                        'woo_instance_id': instance_id.id,
                                        'woo_id': rec.get('id') if rec.get('id') else '',
                                        'name': rec.get('name') if rec.get('name') else '',
                                        'slug': rec.get('slug') if rec.get('slug') else '',
                                    }
                                    if not product_attr:
                                        product_attr = self.env['product.attribute'].sudo().create(dict_attr)
                            
    def import_inventory(self, instance_id):
        page = 1
        location_id = self.env.ref('stock.stock_location_stock').id
        while page > 0 :
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
                data = wcapi.get(url, params={'orderby': 'id', 'order': 'asc', 'per_page': 100, 'page': page})
                page += 1
            except Exception as error:
                raise UserError(_("Please check your connection and try again"))

            if data.status_code == 200 and data.content:
                response = data.json()
                if len(response) == 0:
                    page = 0
                for ele in response:
                    # Repetir para las variantes del producto
                    product_template = self.env['product.template'].sudo().search(
                            ['|', ('woo_id', '=', ele.get('id')), ('default_code', '=', ele.get('sku'))], limit=1)
                    # Si el producto existe en Odoo
                    if product_template:
                        if ele.get('type') == 'variable':
                            # Obtener las variaciones si el producto es variable
                            try:
                                variations_data = wcapi.get(f'products/{product_template.woo_id}/variations')
                                if variations_data.status_code == 200:
                                    variations = variations_data.json()
                                    if not variations:
                                        _logger.warning(f"El producto {product_template.name} no tiene variaciones en WooCommerce.")
                                        continue
                                    for var in variations:
                                        stock_quantity = var.get('stock_quantity')
                                        if stock_quantity is not None and stock_quantity >=0:
                                            product_variant = self.env['product.product'].sudo().search(
                                                ['|', ('woo_id', '=', var.get('id')), ('default_code', '=', var.get('sku'))], limit=1)
                                            if product_variant:
                                                self._update_stock_quantities(product_variant, stock_quantity, location_id)
                            except Exception as error:
                                _logger.error(f"Error al obtener las variantes del producto {product_template.name} desde WooCommerce: {error}")
                                raise UserError(_("Error al obtener las variantes del producto %s desde WooCommerce" % product_template.name ))
                        elif ele.get('type') == 'simple':
                            stock_quantity = ele.get('stock_quantity')
                            if stock_quantity is not None and stock_quantity >=0:
                                product = self.env['product.product'].sudo().search(
                                    ['|', ('woo_id', '=', var.get('id')), ('default_code', '=', var.get('sku'))], limit=1)
                                if product:
                                    self._update_stock_quantities(product, stock_quantity, location_id)
            else:
                page = 0
    
    def _update_stock_quantities(self, product, stock_quantity, location_id):
        """Actualiza las cantidades de stock según si el producto tiene seguimiento por lotes o no."""
        
        if product.tracking != 'none':
            # Procesamos las cantidades de stock por lote
            lots = self.env['stock.lot'].sudo().search(
                [('product_id','=', product.id)], order='create_date asc')
            if not lots:
                _logger.warning(f"No hay lotes disponibles para el producto {product.name}. Creando un nuevo lote.")
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
                    quant.sudo().write({'quantity':quant.quantity + difference})
                else:
                    self.env['stock.quant'].sudo().create({
                        'product_id':product.id,
                        'location_id':location_id,
                        'quantity':difference,
                        'lot_id':oldest_lot.id,
                        'company_id':self.env.company.id
                    })
            elif difference < 0:
                quant = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', product.id),
                    ('location_id', '=', location_id),
                    ('lot_id', '=', oldest_lot.id)
                ], limit=1)
                if quant and quant.quantity >= abs(difference):
                    quant.sudo().write({'quantity': quant.quantity + difference})
                else:
                    raise UserError(_("No se puede reducir más stock del lote más antiguo porque la cantidad es insuficiente."))
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
