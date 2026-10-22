"""A stand-in for the Android Publisher client: enough of edits/tracks/bundles
to exercise promote, rollout, status and upload, and of monetization
(one-time products, their purchase options and offers, subscriptions) to
exercise products plan/apply, without the network."""
import copy
import json


def http_error(status, message):
    """The HttpError googleapiclient raises, with Play's JSON error body."""
    import httplib2
    from googleapiclient.errors import HttpError
    body = json.dumps({'error': {'code': status, 'message': message}}).encode()
    return HttpError(httplib2.Response({'status': status}), body)


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _UploadReq:
    def __init__(self, fn):
        self.fn = fn

    def next_chunk(self, num_retries=0):
        return None, self.fn()


class FakePlay:
    def __init__(self, tracks=None, next_code=100, products=None, offers=None,
                 refuse_active_offer_edits=False, manual_review=False):
        self.tracks_state = copy.deepcopy(tracks or {'internal': [], 'alpha': [], 'beta': [],
                                                      'production': []})
        self.money = FakeMonetization(products, offers, refuse_active_offer_edits)
        self.staged = None
        self.committed = []
        self.deleted = 0
        self.next_code = next_code
        self.commit_kwargs = None
        # Set to model an app with a rejected update or policy issue: Play
        # refuses to send an edit for review unless told not to.
        self.manual_review = manual_review

    # client shape: svc.edits().tracks().get(...).execute()
    def edits(self):
        return self

    # client shape: svc.monetization().onetimeproducts().purchaseOptions().offers()...
    def monetization(self):
        return self.money

    def insert(self, packageName, body):
        def go():
            self.staged = copy.deepcopy(self.tracks_state)
            return {'id': 'edit1'}
        return _Req(go)

    def delete(self, packageName, editId):
        def go():
            self.deleted += 1
            self.staged = None
            return {}
        return _Req(go)

    def _refuse_auto_review(self, kwargs):
        if self.manual_review and not kwargs.get('changesNotSentForReview'):
            raise http_error(400, 'Changes cannot be sent for review automatically. Please set '
                                  'the query parameter changesNotSentForReview to true.')

    def validate(self, packageName, editId):
        # The real client has no changesNotSentForReview on validate.
        def go():
            self._refuse_auto_review({})
            return {}
        return _Req(go)

    def commit(self, packageName, editId, **kwargs):
        def go():
            self._refuse_auto_review(kwargs)
            self.commit_kwargs = kwargs
            self.tracks_state = copy.deepcopy(self.staged)
            self.committed.append(copy.deepcopy(self.staged))
            return {}
        return _Req(go)

    def tracks(self):
        return self

    def list(self, packageName, editId):
        return _Req(lambda: {'tracks': [{'track': t, 'releases': r} for t, r in self.staged.items()]})

    def get(self, packageName, editId, track):
        return _Req(lambda: {'track': track, 'releases': copy.deepcopy(self.staged[track])})

    def update(self, packageName, editId, track, body):
        def go():
            self.staged[track] = copy.deepcopy(body['releases'])
            return body
        return _Req(go)

    def bundles(self):
        outer = self

        class B:
            def upload(self, packageName, editId, media_body):
                def go():
                    outer.next_code += 1
                    return {'versionCode': outer.next_code}
                return _UploadReq(go)
        return B()

    def deobfuscationfiles(self):
        class D:
            def upload(self, **kw):
                return _UploadReq(lambda: {})
        return D()


class FakeMonetization:
    """monetization.* as Play behaves: purchase options and offers are stored
    as DRAFT whatever the body says, and only batchUpdateStates activates
    them. `calls` records every write, in order."""

    def __init__(self, products=None, offers=None, refuse_active_offer_edits=False):
        self.products = copy.deepcopy(products or {})   # productId -> OneTimeProduct
        self.offers = copy.deepcopy(offers or {})       # (productId, optionId, offerId) -> offer
        self.subs = {}
        # Set to model Play refusing to edit an offer once it is live.
        self.refuse_active_offer_edits = refuse_active_offer_edits
        # Regions Play says are not billable at the request's regions version.
        self.unbillable = set()
        self.calls = []

    def onetimeproducts(self):
        return _Products(self)

    def subscriptions(self):
        return _Subscriptions(self)


class _Subscriptions:
    def __init__(self, m):
        self.m = m

    def list(self, packageName, pageToken=None):
        return _Req(lambda: {'subscriptions': list(copy.deepcopy(self.m.subs).values())})


class _Products:
    def __init__(self, m):
        self.m = m

    def get(self, packageName, productId):
        def go():
            if productId not in self.m.products:
                raise http_error(404, f'Product {productId} not found.')
            return copy.deepcopy(self.m.products[productId])
        return _Req(go)

    def list(self, packageName, pageToken=None):
        return _Req(lambda: {'oneTimeProducts': list(copy.deepcopy(self.m.products).values())})

    def patch(self, packageName, productId, body, allowMissing=False, updateMask='',
              regionsVersion_version=None):
        def go():
            self.m.calls.append(('product.patch', productId))
            old = self.m.products.get(productId)
            if old is None and not allowMissing:
                raise http_error(404, f'Product {productId} not found.')
            states = {o['purchaseOptionId']: o.get('state', 'DRAFT')
                      for o in (old or {}).get('purchaseOptions', [])}
            new = copy.deepcopy(body)
            for o in new.get('purchaseOptions', []):
                o['state'] = states.get(o['purchaseOptionId'], 'DRAFT')
            self.m.products[productId] = new
            return copy.deepcopy(new)
        return _Req(go)

    def purchaseOptions(self):
        return _PurchaseOptions(self.m)


class _PurchaseOptions:
    def __init__(self, m):
        self.m = m

    def batchUpdateStates(self, packageName, productId, body):
        def go():
            for r in body['requests']:
                a = r['activatePurchaseOptionRequest']
                self.m.calls.append(('option.activate', productId, a['purchaseOptionId']))
                for o in self.m.products[productId]['purchaseOptions']:
                    if o['purchaseOptionId'] == a['purchaseOptionId']:
                        o['state'] = 'ACTIVE'
            return {}
        return _Req(go)

    def offers(self):
        return _Offers(self.m)


def _merge_mask(old, new, mask):
    out = copy.deepcopy(old)
    for field in [f.strip() for f in mask.split(',') if f.strip()]:
        if field in new:
            out[field] = copy.deepcopy(new[field])
        else:
            out.pop(field, None)
    return out


class _Offers:
    def __init__(self, m):
        self.m = m

    def _option(self, productId, purchaseOptionId):
        product = self.m.products.get(productId)
        if product is None or not any(o['purchaseOptionId'] == purchaseOptionId
                                      for o in product.get('purchaseOptions', [])):
            raise http_error(404, f'Purchase option {productId}/{purchaseOptionId} not found.')

    def list(self, packageName, productId, purchaseOptionId, pageSize=None, pageToken=None):
        def go():
            self._option(productId, purchaseOptionId)
            return {'oneTimeProductOffers': [copy.deepcopy(o) for (p, po, _), o in sorted(self.m.offers.items())
                                             if p == productId and po == purchaseOptionId]}
        return _Req(go)

    def batchGet(self, packageName, productId, purchaseOptionId, body):
        def go():
            out = []
            for r in body['requests']:
                key = (r['productId'], r['purchaseOptionId'], r['offerId'])
                if key not in self.m.offers:
                    raise http_error(404, f'Offer {"/".join(key)} not found.')
                out.append(copy.deepcopy(self.m.offers[key]))
            return {'oneTimeProductOffers': out}
        return _Req(go)

    def batchUpdate(self, packageName, productId, purchaseOptionId, body):
        def go():
            out = []
            for r in body['requests']:
                offer = r['oneTimeProductOffer']
                assert r.get('regionsVersion', {}).get('version'), 'regionsVersion is required'
                assert offer['packageName'] == packageName
                for rc in offer.get('regionalPricingAndAvailabilityConfigs', []):
                    if rc['regionCode'] in self.m.unbillable:
                        raise http_error(400, f"Region code {rc['regionCode']} is not billable at "
                                              f"the specified regions version "
                                              f"{r['regionsVersion']['version']}.")
                self._option(offer['productId'], offer['purchaseOptionId'])
                key = (offer['productId'], offer['purchaseOptionId'], offer['offerId'])
                old = self.m.offers.get(key)
                if old is None:
                    if not r.get('allowMissing'):
                        raise http_error(404, f'Offer {"/".join(key)} not found.')
                    new = copy.deepcopy(offer)
                    new['state'] = 'DRAFT'
                else:
                    if self.m.refuse_active_offer_edits and old.get('state') == 'ACTIVE':
                        raise http_error(400, 'An active offer cannot be modified.')
                    new = _merge_mask(old, offer, r['updateMask'])
                new['regionsVersion'] = copy.deepcopy(r['regionsVersion'])
                self.m.calls.append(('offer.update' if old else 'offer.create', *key))
                self.m.offers[key] = new
                out.append(copy.deepcopy(new))
            return {'oneTimeProductOffers': out}
        return _Req(go)

    def batchUpdateStates(self, packageName, productId, purchaseOptionId, body):
        def go():
            out = []
            for r in body['requests']:
                (kind, a), = r.items()
                key = (a['productId'], a['purchaseOptionId'], a['offerId'])
                if key not in self.m.offers:
                    raise http_error(404, f'Offer {"/".join(key)} not found.')
                state = {'activateOneTimeProductOfferRequest': 'ACTIVE',
                         'deactivateOneTimeProductOfferRequest': 'INACTIVE',
                         'cancelOneTimeProductOfferRequest': 'CANCELLED'}[kind]
                self.m.calls.append((f'offer.{state.lower()}', *key))
                self.m.offers[key]['state'] = state
                out.append(copy.deepcopy(self.m.offers[key]))
            return {'oneTimeProductOffers': out}
        return _Req(go)
