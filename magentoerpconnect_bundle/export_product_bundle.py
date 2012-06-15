# -*- coding: utf-8 -*-
from osv import osv

class export_product(osv.osv_memory):
    _inherit = 'product.export.wizard'

    def export(self, cr, uid, id, option, context=None):
        ret_val = super(export_product, self).export(cr, uid, id, option, context=context)
        if not context.get('active_ids',[]) or option=='export_inventory':
            return ret_val
        product_pool = self.pool.get('product.product')
        external_pool = self.pool.get('external.referential')
        external_referential_id = external_pool.search(cr, uid, [], )[0]
        product_bundle = {}
        shop_ids = self.read(cr, uid, id, context=context)[0]['shop']
        sale_shop_obj = self.pool.get('sale.shop')
        FLG = False
        sel_dict = {}
        again = False
        new_synch_data = []
        for shop in sale_shop_obj.browse(cr, uid, shop_ids, context=context):
            external_referential_id = shop.referential_id.id
            ext_obj = external_pool.browse(cr, uid, external_referential_id, context=context)
            conn = shop.referential_id.external_connection()
            for product_data in product_pool.browse(cr, uid,
                                             context.get('active_ids',[]),
                                                  context=context):

                ext_id = product_pool.oeid_to_extid(cr, uid, product_data.id, external_referential_id,
                                    context=context
                                  )
                if product_data.product_type == 'bundle':
                    again = True
                    product_bundle = {}
                    selection_data = {}
                    item = 0
                    sel_item = 0
                    for item_data in product_data.item_set_ids:
                        if not FLG:
                            option_data = {
                                    'title':item_data.name,
                                    'option_id' : '',
                                    'delete' : 0,
                                    'type' : 'select',
                                    'required' : item_data.required,
                                    'position' : item_data.sequence,
                            }

                        selection_data[str(item)]={}
                        for item_set_data in item_data.item_set_line_ids:
                            ext_pr_id = product_pool.oeid_to_extid(cr, uid, item_set_data.product_id.id, external_referential_id,
                                                context=context
                                              )

                            if not shop.pricelist_id :

                                price = item_set_data.product_id.list_price
                            else:
                                price_list_price = self.pool.get('product.pricelist').price_get(cr, uid, [shop.pricelist_id.id], item_set_data.product_id.id, 1)
                                price = price_list_price[shop.pricelist_id.id]
                            if not FLG:
                                sel_data = {
                                    'selection_id' : '',
                                    'option_id' : '',
                                    'product_id' : ext_pr_id,
                                    'delete' : 0,
                                    'is_default': item_set_data.is_default,
                                    'selection_price_value' : 0,
                                    'selection_price_type' : 0,
                                    'selection_qty' : item_set_data.qty_uom or 0,
                                    'selection_can_change_qty' : item_set_data.allow_chg_qty and 1 or 1,
                                    'position' : item_set_data.sequence,
                                }
                                selection_data[str(item)][str(sel_item)]=sel_data
                                sel_item+=1
                            else:
                                if str(ext_pr_id) not in sel_dict:
                                    continue
                                row_data = sel_dict[str(ext_pr_id)]
                                if row_data['selection_price_value'] == str(price):
                                    continue
                                website_id =  self.pool.get('external.shop.group').oeid_to_extid(cr, uid, shop.shop_group_id.id, external_referential_id,
                                                context=context
                                              )
                                new_synch_data.append({'selection_id':row_data['selection_id'],
                                                       'product_id':ext_pr_id,
                                                       'selection_price_value':price,
                                                       'website_id':website_id})
                        if not FLG:
                            product_bundle[str(item)] = option_data
                        item+=1

                    if not FLG:
                        sel_datas = conn.call('ol_catalog_product.set_bundle_product',[product_bundle,selection_data,ext_id]) or []
                        for sel_data in sel_datas:
                            sel_dict[sel_data['product_id']] = sel_data
                    else :
                        conn.call('ol_catalog_product.set_bundle_selection',[new_synch_data])
        if (option in ('export_inventory' , 'export_product_and_inventory') or \
            'export_inventory' in option or 'export_product_and_inventory' in option) and again:
            ret_val = super(export_product, self).export(cr, uid, id, ['export_inventory'], context=context)
        return ret_val

export_product()
