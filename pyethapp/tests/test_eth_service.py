from builtins import range
from builtins import object
import os
import pytest
from ethereum.db import EphemDB
from ethereum.utils import (
    decode_hex,
    encode_hex,
)
from pyethapp.config import update_config_with_defaults
from pyethapp import eth_service
from pyethapp import leveldb_service
# from pyethapp import codernitydb_service
from pyethapp import eth_protocol
from ethereum import slogging
from ethereum.tools import tester
from ethereum import config as eth_config
from ethereum.transactions import Transaction
import rlp
import tempfile
slogging.configure(config_string=':debug')

empty = object()


class AppMock(object):

    class Services(dict):

        class accounts(object):
            coinbase = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        class peermanager(object):

            @classmethod
            def broadcast(*args, **kwargs):
                pass

    def __init__(self, db=None, config={}):
        self.services = self.Services()
        self.services.db = EphemDB()
        if 'app' not in config:
            config['app'] = dict(dir=tempfile.mkdtemp())
        if 'db' not in config:
            config['db'] = dict(path='_db')
        if 'eth' not in config:
            config['eth'] = dict(
                pruning=-1,
                network_id=1,
                block=eth_config.default_config)
        self.config = config


class PeerMock(object):

    def __init__(self, app):
        self.config = app.config
        self.send_packet = lambda x: x
        self.remote_client_version = empty

newblk_rlp = (
    "f90207f901fef901f9a018632409b5181b4b6508d4b2b2a5463f814ac47bb580c1fe545b4e0"
    "c029c36d8a01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
    "94b8a2bef22b002a4d23206bd737310d0358c66d63a07ee7071f0538e10385f65e5bac1275a"
    "61da60b9c81013b48e1ff43fc12a1c037a056e81f171bcc55a6ff8345e692c0f86e5b48e01b"
    "996cadc001622fb5e363b421a056e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc00"
    "1622fb5e363b421b90100000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "00000000830f4c27823647832fefd88084551c7b5080a06bdda1da3ac7e8f6be01b4d05d417"
    "5f0b5d2a84fef43716c1f16c71d9a32193d881c2ea8eea335e950c0c08502595559e2")

block_1 = (
    "f901f7a0fd4af92a79c7fc2fd8bf0d342f2e832e1d4f485c85b9152d2039e03bc604fdcaa01"
    "dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d493479415caa04a94"
    "07a2f242b2859005a379655bfb9b11a00298b547b494ff85b4750d90ad212269cf642f4fb7e"
    "6b205e461f3e10d18a950a056e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc00162"
    "2fb5e363b421a056e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b"
    "421b90100000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000008302"
    "000001832fefd880845504456080a0839bc994837a59595159fb15605b6db119237c7504edf"
    "5c5853b248700e0789c8872cf25e7727307ba")


fn = 'blocks256.hex.rlp'
p = os.path.join(os.path.dirname(__file__), fn)
data256 = open(p).read()


def test_receive_newblock():
    app = AppMock()
    eth = eth_service.ChainService(app)
    proto = eth_protocol.ETHProtocol(PeerMock(app), eth)
    d = eth_protocol.ETHProtocol.newblock.decode_payload(decode_hex(newblk_rlp))
    eth.on_receive_newblock(proto, **d)


def receive_blockheaders(rlp_data, leveldb=False, codernitydb=False):
    app = AppMock()
    if leveldb:
        app.db = leveldb_service.LevelDB(
            os.path.join(app.config['app']['dir'], app.config['db']['path']))
    # if codernitydb:
    #     app.db = codernitydb_service.CodernityDB(
    #         os.path.join(app.config['app']['dir'], app.config['db']['path']))

    eth = eth_service.ChainService(app)
    proto = eth_protocol.ETHProtocol(PeerMock(app), eth)
    b = eth_protocol.ETHProtocol.blockheaders.decode_payload(rlp_data)
    eth.on_receive_blockheaders(proto, b)


def test_receive_block1():
    rlp_data = rlp.encode([rlp.decode(decode_hex(block_1))])
    receive_blockheaders(rlp_data)


def test_receive_blockheaders_256():
    receive_blockheaders(decode_hex(data256))


def test_receive_blockheaders_256_leveldb():
    receive_blockheaders(decode_hex(data256), leveldb=True)


@pytest.fixture
def test_app(tmpdir):
    config = {
        'eth': {
            'pruning': -1,
            'network_id': 1,
            'block': {  # reduced difficulty, increased gas limit, allocations to test accounts
                'ACCOUNT_INITIAL_NONCE': 0,
                'GENESIS_DIFFICULTY': 1,
                'BLOCK_DIFF_FACTOR': 2,  # greater than difficulty, thus difficulty is constant
                'GENESIS_GAS_LIMIT': 3141592,
                'GENESIS_INITIAL_ALLOC': {
                    encode_hex(tester.accounts[0]): {'balance': 10 ** 24},
                    encode_hex(tester.accounts[1]): {'balance': 10 ** 24},
                    encode_hex(tester.accounts[2]): {'balance': 10 ** 24},
                    encode_hex(tester.accounts[3]): {'balance': 10 ** 24},
                    encode_hex(tester.accounts[4]): {'balance': 10 ** 24},
                }
            }
        }
    }
    update_config_with_defaults(config, {'eth': {'block': eth_config.default_config}})
    app = AppMock(config=config)
    app.chain = eth_service.ChainService(app)
    return app


def test_head_candidate(test_app):
    chainservice = test_app.chain
    assert len(chainservice.head_candidate.transactions) == 0
    for i in range(5):
        tx = make_transaction(tester.keys[i], 0, 0, tester.accounts[2])
        chainservice.add_transaction(tx)
        assert len(chainservice.head_candidate.transactions) == i + 1


def make_transaction(key, nonce, value, to):
    gasprice = 20 * 10**9
    startgas = 500 * 1000
    v, r, s = 0, 0, 0
    data = "foo"
    tx = Transaction(nonce, gasprice, startgas, to, value, data, v, r, s)
    tx.sign(key)
    return tx


def test_query_headers(test_app):
    test_chain = tester.Chain()
    test_chain.mine(30)

    chainservice = test_app.chain
    chainservice.chain = test_chain.chain

    # query_headers(hash_mode, origin_hash, max_hashes, skip, reverse)
    # case 1-1: hash_mode and reverse
    headers = chainservice.query_headers(
        1,
        5,
        0,
        True,
        origin_hash=test_chain.chain.get_block_by_number(10).hash,
    )
    assert len(headers) == 5
    assert headers[0].number == 10
    assert headers[-1].number == 6

    # case 1-2: hash_mode and reverse, reach genesis
    headers = chainservice.query_headers(
        1,
        20,
        0,
        True,
        origin_hash=test_chain.chain.get_block_by_number(10).hash,
    )
    assert len(headers) == 10
    assert headers[0].number == 10
    assert headers[-1].number == 1

    # case 2: hash_mode and not reverse
    headers = chainservice.query_headers(
        1,
        5,
        0,
        False,
        origin_hash=test_chain.chain.get_block_by_number(10).hash,
    )
    assert len(headers) == 5
    assert headers[0].number == 10
    assert headers[-1].number == 14

    # case 3: number mode and reverse
    headers = chainservice.query_headers(
        0,
        5,
        0,
        True,
        number=10,
    )
    assert len(headers) == 5
    assert headers[0].number == 10
    assert headers[-1].number == 6

    # case 4: number mode and not reverse
    headers = chainservice.query_headers(
        0,
        5,
        0,
        False,
        number=10,
    )
    assert len(headers) == 5
    assert headers[0].number == 10
    assert headers[-1].number == 14
