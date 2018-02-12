from builtins import str
from itertools import count
import pytest
import serpent
from devp2p.peermanager import PeerManager
import ethereum
from ethereum.tools import tester
from ethereum.pow.ethpow import mine
import ethereum.tools.keys
import ethereum.config
from ethereum.slogging import get_logger, configure_logging
from ethereum.state import State
from ethereum.utils import encode_hex
from pyethapp.accounts import Account, AccountsService, mk_random_privkey
from pyethapp.app import EthApp
from pyethapp.config import update_config_with_defaults, get_default_config
from pyethapp.db_service import DBService
from pyethapp.eth_service import ChainService
from pyethapp.pow_service import PoWService
from pyethapp.console_service import Console

# reduce key derivation iterations
ethereum.tools.keys.PBKDF2_CONSTANTS['c'] = 100

configure_logging(':trace')
log = get_logger('test.console_service')


@pytest.fixture
def test_app(request, tmpdir):

    class TestApp(EthApp):

        def start(self):
            super(TestApp, self).start()
            log.debug('adding test accounts')
            # high balance account
            self.services.accounts.add_account(Account.new('', tester.keys[0]), store=False)
            # low balance account
            self.services.accounts.add_account(Account.new('', tester.keys[1]), store=False)
            # locked account
            locked_account = Account.new('', tester.keys[2])
            locked_account.lock()
            self.services.accounts.add_account(locked_account, store=False)
            assert set(acct.address for acct in self.services.accounts) == set(tester.accounts[:3])

        def mine_next_block(self):
            """Mine until a valid nonce is found.

            :returns: the new head
            """
            log.debug('mining next block')
            block = self.services.chain.head_candidate
            chain = self.services.chain.chain
            head_number = chain.head.number
            delta_nonce = 10**6
            for start_nonce in count(0, delta_nonce):
                bin_nonce, mixhash = mine(block.number, block.difficulty, block.mining_hash,
                                          start_nonce=start_nonce, rounds=delta_nonce)
                if bin_nonce:
                    break
            self.services.pow.recv_found_nonce(bin_nonce, mixhash, block.mining_hash)
            if len(chain.time_queue) > 0:
                # If we mine two blocks within one second, pyethereum will
                # force the new block's timestamp to be in the future (see
                # ethereum1_setup_block()), and when we try to add that block
                # to the chain (via Chain.add_block()), it will be put in a
                # queue for later processing. Since we need to ensure the
                # block has been added before we continue the test, we
                # have to manually process the time queue.
                log.debug('block mined too fast, processing time queue')
                chain.process_time_queue(new_time=block.timestamp)
            log.debug('block mined')
            assert chain.head.difficulty == 1
            assert chain.head.number == head_number + 1
            return chain.head

    config = {
        'data_dir': str(tmpdir),
        'db': {'implementation': 'EphemDB'},
        'pow': {'activated': False},
        'p2p': {
            'min_peers': 0,
            'max_peers': 0,
            'listen_port': 29873
        },
        'node': {'privkey_hex': encode_hex(mk_random_privkey())},
        'discovery': {
            'boostrap_nodes': [],
            'listen_port': 29873
        },
        'eth': {
            'block': {  # reduced difficulty, increased gas limit, allocations to test accounts
                'GENESIS_DIFFICULTY': 1,
                'BLOCK_DIFF_FACTOR': 2,  # greater than difficulty, thus difficulty is constant
                'GENESIS_GAS_LIMIT': 3141592,
                'GENESIS_INITIAL_ALLOC': {
                    encode_hex(tester.accounts[0]): {'balance': 10**24},
                    encode_hex(tester.accounts[1]): {'balance': 1},
                    encode_hex(tester.accounts[2]): {'balance': 10**24},
                }
            }
        },
        'jsonrpc': {'listen_port': 29873}
    }
    services = [DBService, AccountsService, PeerManager, ChainService, PoWService, Console]
    update_config_with_defaults(config, get_default_config([TestApp] + services))
    update_config_with_defaults(config, {'eth': {'block': ethereum.config.default_config}})
    app = TestApp(config)
    for service in services:
        service.register_with_app(app)

    def fin():
        log.debug('stopping test app')
        app.stop()
    request.addfinalizer(fin)

    log.debug('starting test app')
    app.start()
    return app


def test_send_transaction_with_contract(test_app):
    serpent_code = '''
def main(a,b):
    return(a ^ b)
'''
    tx_to = b''
    evm_code = serpent.compile(serpent_code)
    chain = test_app.services.chain.chain
    chainservice = test_app.services.chain
    hc_state = State(chainservice.head_candidate.state_root, chain.env)
    sender = test_app.services.accounts.unlocked_accounts[0].address
    assert hc_state.get_balance(sender) > 0

    eth = test_app.services.console.console_locals['eth']
    tx = eth.transact(to='', data=evm_code, startgas=500000, sender=sender)

    hc_state_dict = State(chainservice.head_candidate.state_root, chain.env).to_dict()
    code = hc_state_dict[encode_hex(tx.creates)]['code']
    assert len(code) > 2
    assert code != '0x'

    test_app.mine_next_block()

    creates = chain.head.transactions[0].creates
    code = chain.state.to_dict()[encode_hex(creates)]['code']
    assert len(code) > 2
    assert code != '0x'


def test_console_name_reg_contract(test_app):
    """
    exercise the console service with the NameReg contract found in The_Console wiki
    https://github.com/ethereum/pyethapp/wiki/The_Console#creating-contracts
    """

    solidity_code = """
    contract NameReg  {
       event AddressRegistered(bytes32 indexed name, address indexed account);
       mapping (address => bytes32) toName;

       function register(bytes32 name) {
               toName[msg.sender] = name;
               AddressRegistered(name, msg.sender);
       }

       function resolve(address addr) constant returns (bytes32 name) {
               return toName[addr];
       }
    }
    """

    import ethereum.tools._solidity
    solidity = ethereum.tools._solidity.get_solidity()
    if solidity is None:
        pytest.xfail("solidity not installed, not tested")
    else:
        # create the NameReg contract
        tx_to = b''
        evm_code = solidity.compile(solidity_code)
        chainservice = test_app.services.chain
        chain = test_app.services.chain.chain
        hc_state = State(chainservice.head_candidate.state_root, chain.env)
        sender = test_app.services.accounts.unlocked_accounts[0].address
        assert hc_state.get_balance(sender) > 0

        eth = test_app.services.console.console_locals['eth']
        tx = eth.transact(to='', data=evm_code, startgas=500000, sender=sender)

        hc_state_dict = State(chainservice.head_candidate.state_root, chain.env).to_dict()
        code = hc_state_dict[encode_hex(tx.creates)]['code']
        assert len(code) > 2
        assert code != '0x'

        test_app.mine_next_block()

        creates = chain.head.transactions[0].creates
        state_dict = chain.state.to_dict()
        code = state_dict[encode_hex(creates)]['code']
        assert len(code) > 2
        assert code != '0x'

        # interact with the NameReg contract
        abi = solidity.mk_full_signature(solidity_code)
        namereg = eth.new_contract(abi, creates, sender=sender)

        register_tx = namereg.register('alice', startgas=90000, gasprice=50 * 10**9)

        test_app.mine_next_block()

        result = namereg.resolve(sender)
        assert result == b'alice' + ('\x00' * 27).encode()
