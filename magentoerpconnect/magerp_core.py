# -*- encoding: utf-8 -*-
#########################################################################
#This module intergrates Open ERP with the magento core                 #
#Core settings are stored here                                          #
#########################################################################
#                                                                       #
# Copyright (C) 2009  Sharoon Thomas                                    #
# Copyright (C) 2011 Akretion Sébastien BEAU sebastien.beau@akretion.com#
# Copyright (C) 2011 Camptocamp Guewen Baconnier                        #
#                                                                       #
#This program is free software: you can redistribute it and/or modify   #
#it under the terms of the GNU General Public License as published by   #
#the Free Software Foundation, either version 3 of the License, or      #
#(at your option) any later version.                                    #
#                                                                       #
#This program is distributed in the hope that it will be useful,        #
#but WITHOUT ANY WARRANTY; without even the implied warranty of         #
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          #
#GNU General Public License for more details.                           #
#                                                                       #
#You should have received a copy of the GNU General Public License      #
#along with this program.  If not, see <http://www.gnu.org/licenses/>.  #
#########################################################################

from osv import osv, fields
import magerp_osv
import pooler
import netsvc
import base64, urllib
from magerp_osv import Connection
import tools
from tools.translate import _
import os

DEBUG = True
TIMEOUT = 2

import logging

class external_referential(magerp_osv.magerp_osv):
    #This class stores instances of magento to which the ERP will connect, so you can connect OpenERP to multiple Magento installations (eg different Magento databases)
    _inherit = "external.referential"

    _logger = logging.getLogger(__name__)
    SYNC_PRODUCT_FILTERS = {'status': {'=': 1}}
    SYNC_PARTNER_FILTERS = {}
    SYNC_PARTNER_STEP = 500

    def _is_magento_referential(self, cr, uid, ids, field_name, arg, context=None):
        """If at least one shop is magento, we consider that the external
        referential is a magento referential
        """
        res = {}
        for referential in self.browse(cr, uid, ids, context):
            res[referential.id] = False
            for group in referential.shop_group_ids:
                for shop in group.shop_ids:
                    if shop.magento_shop:
                        res[referential.id] = True
                        break
                if res[referential.id]:
                    break
        return res

    _columns = {
        'attribute_sets':fields.one2many('magerp.product_attribute_set', 'referential_id', 'Attribute Sets'),
        'default_pro_cat':fields.many2one('product.category','Default Product Category', help="Products imported from magento may have many categories.\nOpenERP requires a specific category for a product to facilitate invoicing etc."),
        'default_lang_id':fields.many2one('res.lang', 'Default Language', help="Choose the language which will be used for the Default Value in Magento"),
        'active': fields.boolean('Active'),
        'magento_referential': fields.function(_is_magento_referential, type="boolean", method=True, string="Magento Referential"),
        'last_imported_product_id': fields.integer('Last Imported Product Id', help="Product are imported one by one. This is the magento id of the last product imported. If you clear it all product will be imported"),
        'last_imported_partner_id': fields.integer('Last Imported Partner Id', help="Partners are imported one by one. This is the magento id of the last partner imported. If you clear it all partners will be imported"),
        'import_all_attributs': fields.boolean('Import all attributs', help="If the option is uncheck only the attributs that doesn't exist in OpenERP will be imported"), 
        'import_image_with_product': fields.boolean('With image', help="If the option is check the product's image and the product will be imported at the same time and so the step '7-import images' is not needed"),
        'import_links_with_product': fields.boolean('With links', help="If the option is check the product's links (Up-Sell, Cross-Sell, Related) and the product will be imported at the same time and so the step '8-import links' is not needed"),
    }

    _defaults = {
        'active': lambda *a: 1,
    }

    def external_connection(self, cr, uid, id, DEBUG=False, context=None):
        if isinstance(id, list):
            id=id[0]
        referential = self.browse(cr, uid, id)
        if 'magento' in referential.type_id.name.lower():
            attr_conn = Connection(referential.location, referential.apiusername, referential.apipass, DEBUG)
            return attr_conn.connect() and attr_conn or False
        else:
            return super(external_referential, self).external_connection(cr, uid, id, DEBUG=DEBUG, context=context)

    def connect(self, cr, uid, id, context=None):
        if isinstance(id, (list, tuple)):
            if not len(id) == 1:
                raise osv.except_osv(_("Error"), _("Connect should be only call with one id"))
            else:
                id = id[0]
            core_imp_conn = self.external_connection(cr, uid, id, DEBUG, context=context)
            if core_imp_conn.connect():
                return core_imp_conn
            else:
                raise osv.except_osv(_("Connection Error"), _("Could not connect to server\nCheck location, username & password."))

        return False

    def core_sync(self, cr, uid, ids, context=None):
        filter = []
        for referential_id in ids:
            core_imp_conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
            self.pool.get('external.shop.group').mage_import_base(cr, uid,core_imp_conn, referential_id, defaults={'referential_id':referential_id})
            self.pool.get('sale.shop').mage_import_base(cr, uid, core_imp_conn, referential_id, {'magento_shop':True, 'company_id':self.pool.get('res.users').browse(cr, uid, uid).company_id.id})
            self.pool.get('magerp.storeviews').mage_import_base(cr,uid,core_imp_conn, referential_id, defaults={})
        return True

    def sync_categs(self, cr, uid, ids, context=None):
        for referential_id in ids:
            pro_cat_conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
            confirmation = pro_cat_conn.call('catalog_category.currentStore', [0])   #Set browse to root store
            if confirmation:
                categ_tree = pro_cat_conn.call('catalog_category.tree')             #Get the tree
                self.pool.get('product.category').record_entire_tree(cr, uid, referential_id, pro_cat_conn, categ_tree, DEBUG)
                #exp_ids = self.pool.get('product.category').search(cr,uid,[('exportable','=',True)])
                #self.pool.get('product.category').ext_export(cr,uid,exp_ids,[referential_id],{},{'conn_obj':pro_cat_conn})
        return True

    def sync_attribs(self, cr, uid, ids, context=None):
        attr_obj = self.pool.get('magerp.product_attributes')
        attr_set_obj = self.pool.get('magerp.product_attribute_set')
        for referential in self.browse(cr, uid, ids, context=context):
            attr_conn = referential.external_connection(DEBUG, context=context)
            attrib_set_ids = attr_set_obj.search(cr, uid, [('referential_id', '=', referential.id)])
            attrib_sets = attr_set_obj.read(cr, uid, attrib_set_ids, ['magento_id'])
            #Get all attribute set ids to get all attributes in one go
            all_attr_set_ids = attr_set_obj.get_all_extid_from_referential(cr, uid, referential.id, context=context)
            #Call magento for all attributes
            if referential.import_all_attributs:
                attributes_imported=[]
            else:
                attributes_imported = attr_obj.get_all_extid_from_referential(cr, uid, referential.id, context=context)
            import_cr = pooler.get_db(cr.dbname).cursor()
            try:
                for attr_set_id in all_attr_set_ids:
                    mage_inp = attr_conn.call('ol_catalog_product_attribute.list', [attr_set_id])             #Get the tree
                    attribut_to_import = []
                    for attribut in mage_inp:
                        ext_id = attribut['attribute_id']
                        if not ext_id in attributes_imported:
                            attributes_imported.append(ext_id)
                            attr_obj.ext_import(import_cr, uid, [attribut], referential.id, defaults={'referential_id':referential.id}, context={'referential_id':referential.id})
                            import_cr.commit()
                    self._logger.info("All attributs for the attributs set id %s was succesfully imported" %(attr_set_id))
                #Relate attribute sets & attributes
                mage_inp = {}
                #Pass in {attribute_set_id:{attributes},attribute_set_id2:{attributes}}
                #print "Attribute sets are:", attrib_sets
                #TODO find a solution in order to import the relation in a incremental way (maybe splitting this function in two)
                for each in attrib_sets:
                    mage_inp[each['magento_id']] = attr_conn.call('ol_catalog_product_attribute.relations', [each['magento_id']])
                if mage_inp:
                    attr_set_obj.relate(import_cr, uid, mage_inp, referential.id, DEBUG)
                import_cr.commit()
            finally:
                import_cr.close()
        return True

    def sync_attrib_sets(self, cr, uid, ids, context=None):
        for referential_id in ids:
            attr_conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
            filter = []
            self.pool.get('magerp.product_attribute_set').mage_import_base(cr, uid, attr_conn, referential_id,{'referential_id':referential_id},{'ids_or_filter':filter})
        return True

    def sync_attrib_groups(self, cr, uid, ids, context=None):
        for referential_id in ids:
            attr_conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
            attrset_ids = self.pool.get('magerp.product_attribute_set').get_all_mage_ids(cr, uid, [], referential_id)
            filter = [{'attribute_set_id':{'in':attrset_ids}}]
            self.pool.get('magerp.product_attribute_groups').mage_import_base(cr, uid, attr_conn, referential_id, {'referential_id': referential_id}, {'ids_or_filter':filter})
        return True

    def sync_customer_groups(self, cr, uid, ids, context=None):
        for referential_id in ids:
            attr_conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
            filter = []
            self.pool.get('res.partner.category').mage_import_base(cr, uid, attr_conn, referential_id, {}, {'ids_or_filter':filter})
        return True

    def sync_customer_addresses(self, cr, uid, ids, context=None):
        for referential_id in ids:
            attr_conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
            filter = []
            #self.pool.get('res.partner').mage_import(cr, uid, filter, attr_conn, referential_id, DEBUG)
            #TODO fix by retrieving customer list first
            self.pool.get('res.partner.address').mage_import_base(cr, uid, attr_conn, referential_id, {}, {'ids_or_filter':filter})
        return True

    def _sync_product_storeview(self, cr, uid, referential_id, mag_connection, ext_product_id, storeview, context=None):
        if context is None: context = {}
        #we really need to clean all magento call and give the posibility to force everythere to use the id as identifier
        product_info = mag_connection.call('catalog_product.info', [ext_product_id, storeview.code, False, 'id'])
        ctx = context.copy()
        ctx.update({'magento_sku': product_info['sku']})
        defaults={'magento_exportable': True}
        return self.pool.get('product.product').ext_import(cr, uid, [product_info], referential_id, defaults=defaults , context=ctx)

    def sync_products(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        prod_obj = self.pool.get('product.product')
#        context.update({'dont_raise_error': True})
        for referential in self.browse(cr, uid, ids, context):
            attr_conn = referential.external_connection(DEBUG)
            filter = []
            if referential.last_imported_product_id:
                filters = {'product_id': {'gt': referential.last_imported_product_id}}
                filters.update(self.SYNC_PRODUCT_FILTERS)
                filter = [filters]
            #TODO call method should be not harcoded. Need refactoring
            ext_product_ids = attr_conn.call('ol_catalog_product.search', filter)
            ext_product_ids = [x['product_id'] for x in ext_product_ids]
            storeview_obj = self.pool.get('magerp.storeviews')

            #get all instance storeviews
            storeview_ids = []
            for website in referential.shop_group_ids:
                for shop in website.shop_ids:
                    for storeview in shop.storeview_ids:
                        storeview_ids += [storeview.id]

            lang_2_storeview={}
            for storeview in storeview_obj.browse(cr, uid, storeview_ids, context):
                #get lang of the storeview
                lang_id = storeview.lang_id
                if lang_id:
                    lang = lang_id.code
                else:
                    osv.except_osv(_('Warning!'), _('The storeviews have no language defined'))
                    lang = referential.default_lang_id.code
                if not lang_2_storeview.get(lang, False):
                    lang_2_storeview[lang] = storeview

            if referential.import_links_with_product:
                link_types = self.get_magento_product_link_types(cr, uid, referential.id, attr_conn, context=context)

            import_cr = pooler.get_db(cr.dbname).cursor()
            try:
                for ext_product_id in ext_product_ids:
                    for lang, storeview in lang_2_storeview.iteritems():
                        ctx = context.copy()
                        ctx.update({'lang': lang})
                        res = self._sync_product_storeview(import_cr, uid, referential.id, attr_conn, ext_product_id, storeview, context=ctx)
                    product_id = (res.get('create_ids') or res.get('write_ids'))[0]
                    if referential.import_image_with_product:
                        prod_obj.import_product_image(import_cr, uid, product_id, referential.id, attr_conn, ext_id=ext_product_id, context=context)
                    if referential.import_links_with_product:
                        prod_obj.mag_import_product_links_types(import_cr, uid, product_id, link_types, referential.id, attr_conn, context=context)
                    self.write(import_cr, uid, referential.id, {'last_imported_product_id': int(ext_product_id)}, context=context)
                    import_cr.commit()
            finally:
                import_cr.close()
        return True

    def get_magento_product_link_types(self, cr, uid, ids, conn=None, context=None):
        if not conn:
            conn = self.external_connection(cr, uid, ids, DEBUG, context=context)
        return conn.call('catalog_product_link.types')

    def sync_images(self, cr, uid, ids, context=None):
        product_obj = self.pool.get('product.product')
        image_obj = self.pool.get('product.images')
        import_cr = pooler.get_db(cr.dbname).cursor()
        try:
            for referential_id in ids:
                conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
                product_ids = product_obj.get_all_oeid_from_referential(cr, uid, referential_id, context=context)
                for product_id in product_ids:
                    product_obj.import_product_image(import_cr, uid, product_id, referential_id, conn, context=context)
                    import_cr.commit()
        finally:
            import_cr.close()
        return True

    def sync_product_links(self, cr, uid, ids, context=None):
        if context is None: context = {}
        for referential in self.browse(cr, uid, ids, context):
            conn = referential.external_connection(DEBUG)
            exportable_product_ids= []
            for shop_group in referential.shop_group_ids:
                for shop in shop_group.shop_ids:
                    exportable_product_ids.extend([product.id for product in shop.exportable_product_ids])
            exportable_product_ids = list(set(exportable_product_ids))
            self.pool.get('product.product').mag_import_product_links(cr, uid, exportable_product_ids, referential.id, conn, context=context)
        return True

    def export_products(self, cr, uid, ids, context=None):
        if context is None: context = {}
        shop_ids = self.pool.get('sale.shop').search(cr, uid, [])
        for referential_id in ids:
            for shop in self.pool.get('sale.shop').browse(cr, uid, shop_ids, context):
                context['conn_obj'] = self.external_connection(cr, uid, referential_id, context=context)
                #shop.export_catalog
                tools.debug((cr, uid, shop, context,))
                shop.export_products(cr, uid, shop, context)
        return True

    def sync_partner(self, cr, uid, ids, context=None):
        def next_partners(connection, start, step):
            filters = {'customer_id': {'in': range(start, start + step)}}
            filters.update(self.SYNC_PARTNER_FILTERS)
            filter = [filters]
            return attr_conn.call('customer.list', filter)

        for referential in self.browse(cr, uid, ids, context):
            attr_conn = referential.external_connection(DEBUG)
            last_imported_id = 0
            if referential.last_imported_partner_id:
                last_imported_id = referential.last_imported_partner_id

            ext_customer_ids = next_partners(attr_conn, last_imported_id + 1, self.SYNC_PARTNER_STEP)
            import_cr = pooler.get_db(cr.dbname).cursor()
            try:
                while ext_customer_ids:
                    for ext_customer_id in ext_customer_ids:
                        customer_info = attr_conn.call('customer.info', [ext_customer_id['customer_id']])
                        customer_address_info = attr_conn.call('customer_address.list', [ext_customer_id['customer_id']])

                        address_info = False
                        if customer_address_info:
                            address_info = customer_address_info[0]
                            address_info['customer_id'] = ext_customer_id['customer_id']
                            address_info['email'] = customer_info['email']

                        self.pool.get('res.partner').ext_import(import_cr, uid, [customer_info], referential.id, context=context)
                        if address_info:
                            self.pool.get('res.partner.address').ext_import(import_cr, uid, [address_info], referential.id, context=context)

                        last_imported_id = int(ext_customer_id['customer_id'])
                        self.write(import_cr, uid, referential.id, {'last_imported_partner_id': last_imported_id}, context=context)
                        import_cr.commit()
                    ext_customer_ids = next_partners(attr_conn, last_imported_id + 1, self.SYNC_PARTNER_STEP)
            finally:
                import_cr.close()
        return True

    def sync_newsletter(self, cr, uid, ids, context=None):
        #update first all customer
        self.sync_partner(cr, uid, ids, context)

        partner_obj = self.pool.get('res.partner')

        for referential_id in ids:
            attr_conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
            filter = []
            list_subscribers = attr_conn.call('ol_customer_subscriber.list')
            result = []
            for each in list_subscribers:
                each_subscribers_info = attr_conn.call('ol_customer_subscriber.info', [each])

                # search this customer. If exist, update your newsletter subscription
                partner_ids = partner_obj.search(cr, uid, [('emailid', '=', each_subscribers_info[0]['subscriber_email'])])
                if partner_ids:
                    #unsubscriber magento value: 3
                    if int(each_subscribers_info[0]['subscriber_status']) == 1:
                        subscriber_status = 1
                    else:
                        subscriber_status = 0
                    partner_obj.write(cr, uid, partner_ids[0], {'mag_newsletter': subscriber_status})
        return True

    def sync_newsletter_unsubscriber(self, cr, uid, ids, context=None):
        partner_obj = self.pool.get('res.partner')

        for referential_id in ids:
            attr_conn = self.external_connection(cr, uid, referential_id, DEBUG, context=context)
            partner_ids  = partner_obj.search(cr, uid, [('mag_newsletter', '!=', 1), ('emailid', '!=', '')])

            print partner_ids

            for partner in partner_obj.browse(cr, uid, partner_ids):
                print partner.emailid
                if partner.emailid:
                    attr_conn.call('ol_customer_subscriber.delete', [partner.emailid])

        return True

    # Schedules functions ============ #
    def run_import_newsletter_scheduler(self, cr, uid, context=None):
        if context is None:
            context = {}

        referential_ids  = self.search(cr, uid, [('active', '=', 1)])

        if referential_ids:
            self.sync_newsletter(cr, uid, referential_ids, context)
        if DEBUG:
            print "run_import_newsletter_scheduler: %s" % referential_ids

    def run_import_newsletter_unsubscriber_scheduler(self, cr, uid, context=None):
        if context is None:
            context = {}

        referential_ids  = self.search(cr, uid, [('active', '=', 1)])

        if referential_ids:
            self.sync_newsletter_unsubscriber(cr, uid, referential_ids, context)
        if DEBUG:
            print "run_import_newsletter_unsubscriber_scheduler: %s" % referential_ids

external_referential()


class external_shop_group(magerp_osv.magerp_osv):
    _inherit = "external.shop.group"
    #Return format of API:{'code': 'base', 'name': 'Main', 'website_id': '1', 'is_default': '1', 'sort_order': '0', 'default_group_id': '1'}
    # default_group_id is the default shop of the external_shop_group (external_shop_group = website)

    def _get_default_shop_id(self, cr, uid, ids, prop, unknow_none, context=None):
        res = {}
        for shop_group in self.browse(cr, uid, ids, context):
            if shop_group.default_shop_integer_id:
                rid = self.pool.get('sale.shop').extid_to_oeid(cr, uid, shop_group.default_shop_integer_id, shop_group.referential_id.id)
                res[shop_group.id] = rid
            else:
                res[shop_group.id] = False
        return res

    _columns = {
        'code':fields.char('Code', size=100),
        'is_default':fields.boolean('Is Default?'),
        'sort_order':fields.integer('Sort Order'),
        'default_shop_integer_id':fields.integer('Default Store'), #This field can't be a many2one because shop_group field will be mapped before creating Shop (Shop = Store, shop_group = website)
        'default_shop_id':fields.function(_get_default_shop_id, type="many2one", relation="sale.shop", method=True, string="Default Store"),
        'referential_type' : fields.related('referential_id', 'type_id', type='many2one', relation='external.referential.type', string='External Referential Type'),
    }

external_shop_group()


class magerp_storeviews(magerp_osv.magerp_osv):
    _name = "magerp.storeviews"
    _description = "The magento store views information"

    _columns = {
        'name':fields.char('Store View Name', size=100),
        'code':fields.char('Code', size=100),
        'website_id':fields.many2one('external.shop.group', 'Website', select=True, ondelete='cascade'),
        'is_active':fields.boolean('Default ?'),
        'sort_order':fields.integer('Sort Order'),
        'shop_id':fields.many2one('sale.shop', 'Shop', select=True, ondelete='cascade'),
        'lang_id':fields.many2one('res.lang', 'Language'),
    }

    #Return format of API:{'code': 'default', 'store_id': '1', 'website_id': '1', 'is_active': '1', 'sort_order': '0', 'group_id': '1', 'name': 'Default Store View'}

magerp_storeviews()
